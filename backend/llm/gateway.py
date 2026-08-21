"""Governed provider-neutral model gateway execution."""

from __future__ import annotations

import logging
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Iterator

from backend.llm.contracts import (
    AttemptTelemetry,
    EstimatedCost,
    ExecutionMetadata,
    ModelCapabilityId,
    ModelErrorCode,
    ModelRequest,
    ModelResponse,
    StreamChunk,
    StreamingModelProvider,
    TokenUsage,
)
from backend.llm.errors import (
    ModelBudgetExceededError,
    ModelGatewayError,
    ModelInvalidRequestError,
    ModelProviderError,
    ModelProviderNotConfiguredError,
    ModelUnsupportedCapabilityError,
    redact_error_message,
    redacted_gateway_error,
)
from backend.llm.gateway_state import (
    GatewayBudget,
    PreparedTarget,
    TelemetrySink,
    check_call_limit,
    check_usage_limits,
)
from backend.llm.model_config import ModelConfig, ModelTarget
from backend.llm.registry import ModelProviderRegistry

if TYPE_CHECKING:
    from backend.observability.tracing import ModelCallTrace

logger = logging.getLogger(__name__)


@contextmanager
def _model_trace(
    *,
    agent_id: str,
    provider: str,
    model: str,
    fallback_attempt: int,
    set_current: bool = True,
    run_id: str = "",
    tenant_id: str = "",
) -> Iterator["ModelCallTrace"]:
    """Open a model span, importing observability lazily.

    ``backend.observability.tracing`` imports ``backend.config``, which imports
    ``backend.llm.factory`` and therefore this package. Importing the tracer at
    call time keeps that cycle from breaking any entrypoint whose first backend
    import is ``backend.observability``.

    Yields:
        Mutable span measurements for the attempt.
    """
    from backend.observability.tracing import trace_model_call

    with trace_model_call(
        agent_id=agent_id,
        provider=provider,
        model=model,
        fallback_attempt=fallback_attempt,
        set_current=set_current,
        run_id=run_id,
        tenant_id=tenant_id,
    ) as measurements:
        yield measurements


def _span_error_code(error: BaseException) -> str:
    """Return the code the span should carry for this failure.

    ``GeneratorExit`` yields an empty code: it means the consumer stopped
    iterating, not that the provider failed, so the attempt must not be marked
    as an error on the span.

    Only a ``ModelGatewayError`` is trusted for its own code, mirroring
    ``redacted_gateway_error``. A third-party provider may attach an arbitrary
    ``.code`` to a plain exception; reading it here would put ``timeout`` on the
    span while the caller, the telemetry record, and the fallback decision all
    saw ``provider_error`` -- three channels disagreeing about one attempt.
    """
    if isinstance(error, GeneratorExit):
        return ""
    if isinstance(error, ModelGatewayError):
        code = getattr(error, "code", None)
        return code if isinstance(code, str) else "provider_error"
    return "provider_error"


@dataclass(frozen=True)
class RetryBackoff:
    """Small exponential backoff with jitter applied between same-target retries.

    Defaults to no delay at all (``base_seconds=0.0``), which preserves the
    gateway's previous immediate-retry behavior for every caller that does not
    explicitly configure a backoff policy.

    Attributes:
        base_seconds: Delay before the first retry. ``0`` disables backoff.
        factor: Exponential growth factor applied per additional retry.
        max_seconds: Upper bound on the computed delay, before jitter.
        jitter_seconds: Upper bound of extra uniform random delay added on top.
    """

    base_seconds: float = 0.0
    factor: float = 2.0
    max_seconds: float = 5.0
    jitter_seconds: float = 0.0

    def delay_for(self, retry_index: int) -> float:
        """Return the delay, in seconds, before retrying at ``retry_index``."""
        if self.base_seconds <= 0:
            return 0.0
        delay = min(self.base_seconds * (self.factor**retry_index), self.max_seconds)
        if self.jitter_seconds > 0:
            delay += random.uniform(0.0, self.jitter_seconds)
        return delay


class AttemptOutcome(Enum):
    """Decision produced by the shared attempt coordinator after a failure."""

    RETRY = "retry"
    FALLBACK = "fallback"
    FAIL = "fail"


class _AttemptCoordinator:
    """Attempt bookkeeping shared by ``complete()`` and ``_stream_prepared()``.

    Owns target iteration accounting (budget, attempt numbering), capability-
    error recording, call/usage limit checks, and the retry/fallback/fail
    decision. Mode-specific execution -- issuing the provider call and, for
    streaming, emitting chunks as they arrive -- stays in the caller: forcing
    that into a shared method would either buffer the whole stream (defeating
    partial emission) or leak generator control flow into a plain method.
    """

    def __init__(
        self,
        gateway: "ModelGateway",
        config: ModelConfig,
        prepared: tuple[PreparedTarget, ...],
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._prepared = prepared
        self.budget = GatewayBudget()
        self.attempt_number = 0

    def capability_error_outcome(
        self, target_index: int, item: PreparedTarget
    ) -> AttemptOutcome:
        """Record a preflight capability failure and decide how to proceed.

        Capability errors never consume a call from the budget: no provider
        was invoked.
        """
        self.attempt_number += 1
        self._gateway._record(
            AttemptTelemetry(
                attempt=self.attempt_number,
                provider=item.target.provider or "",
                model=item.target.name,
                duration_ms=0.0,
                error_code="unsupported_capability",
            )
        )
        if self._gateway._can_recover(
            "unsupported_capability", self._config, target_index, self._prepared
        ):
            return AttemptOutcome.FALLBACK
        return AttemptOutcome.FAIL

    def admit_call(self, item: PreparedTarget) -> None:
        """Enforce the call-count ceiling, then account the call and attempt.

        Raises before either counter advances, and before any telemetry is
        recorded, so a call-limit breach never appears as a failed attempt --
        it fails the operation directly, matching the previous inline check.
        """
        check_call_limit(self._config.limits, self.budget, item.target)
        self.budget.calls += 1
        self.attempt_number += 1

    def account_success(
        self, item: PreparedTarget, duration_ms: float, usage: TokenUsage, cost: EstimatedCost
    ) -> None:
        """Account a successful attempt's usage/cost and enforce its timeout.

        Accounting happens before the timeout check: a slow or over-budget
        attempt was still billed by the provider, so it must not be free to
        the budget just because it is about to be rejected.
        """
        self.budget.tokens += usage.total_tokens
        self.budget.cost_usd += cost.usd
        _check_timeout(duration_ms, item.target)

    def enforce_usage_limits(self, item: PreparedTarget) -> None:
        """Fail closed if the accounted budget has crossed a configured ceiling."""
        check_usage_limits(self._config.limits, self.budget, item.target)

    def check_projected_usage(
        self, item: PreparedTarget, usage: TokenUsage, cost: EstimatedCost
    ) -> None:
        """Fail closed against a *projected* budget without mutating the real one.

        Used mid-stream, before a chunk is yielded to the caller: streaming
        must not hand out output that the aggregate budget cannot afford, but
        the real budget is only updated once the attempt's final usage/cost is
        known.
        """
        projected = GatewayBudget(
            calls=self.budget.calls,
            tokens=self.budget.tokens + usage.total_tokens,
            cost_usd=self.budget.cost_usd + cost.usd,
        )
        check_usage_limits(self._config.limits, projected, item.target)

    def record_success(
        self,
        item: PreparedTarget,
        duration_ms: float,
        usage: TokenUsage,
        cost: EstimatedCost,
    ) -> None:
        """Record telemetry for a completed, limit-checked attempt."""
        self._gateway._record(
            AttemptTelemetry(
                attempt=self.attempt_number,
                provider=item.target.provider or "",
                model=item.target.name,
                duration_ms=duration_ms,
                usage=usage,
                cost=cost,
            )
        )

    def decide_failure(
        self,
        exc: Exception,
        item: PreparedTarget,
        target_index: int,
        retry_index: int,
        retries: int,
        *,
        duration_ms: float,
        usage: TokenUsage,
        cost: EstimatedCost,
        mid_stream_emitted: bool = False,
    ) -> tuple[AttemptOutcome, ModelGatewayError]:
        """Redact, record, and classify one failed attempt.

        Decision order mirrors the gateway's previous inline logic exactly:
        a budget breach always fails; a stream that already emitted output to
        the caller can no longer retry or fall back; a configured, still-
        retryable error retries the same target; otherwise policy may allow
        falling back to the next target; anything left fails.
        """
        error = redacted_gateway_error(
            exc, provider=item.target.provider or "", model=item.target.name
        )
        self._gateway._record(
            AttemptTelemetry(
                attempt=self.attempt_number,
                provider=item.target.provider or "",
                model=item.target.name,
                duration_ms=duration_ms,
                usage=usage,
                cost=cost,
                error_code=error.code,
            )
        )
        if isinstance(error, ModelBudgetExceededError):
            return AttemptOutcome.FAIL, error
        if mid_stream_emitted:
            return AttemptOutcome.FAIL, error
        if error.code in self._config.fallback_on and retry_index < retries:
            return AttemptOutcome.RETRY, error
        if self._gateway._can_recover(error.code, self._config, target_index, self._prepared):
            return AttemptOutcome.FALLBACK, error
        return AttemptOutcome.FAIL, error

    def backoff_before_retry(self, retry_index: int) -> None:
        """Sleep the configured backoff delay before retrying the same target."""
        delay = self._gateway._retry_backoff.delay_for(retry_index)
        if delay > 0:
            time.sleep(delay)


class ModelGateway:
    """Apply capability, retry, fallback, limit, and telemetry policy."""

    def __init__(
        self,
        registry: ModelProviderRegistry,
        *,
        telemetry_sink: TelemetrySink | None = None,
        retry_backoff: RetryBackoff | None = None,
    ) -> None:
        """Initialize the gateway.

        Args:
            registry: Provider registry used for every target.
            telemetry_sink: Optional callback receiving safe attempt telemetry.
            retry_backoff: Delay policy applied between same-target retries.
                Defaults to no delay, preserving prior immediate-retry behavior.
        """
        self._registry = registry
        self._telemetry_sink = telemetry_sink
        self._retry_backoff = retry_backoff or RetryBackoff()
        self._state = threading.local()

    @property
    def attempts(self) -> tuple[AttemptTelemetry, ...]:
        """Return telemetry for this thread's most recent gateway operation.

        Attempt telemetry is thread-local, so a gateway instance shared between
        threads never interleaves one operation's attempts into another's.

        This is a convenience for ``complete()``. It is **not** reliable for
        ``stream()``: a generator body runs on whichever thread calls ``next()``,
        so a stream consumed on a worker thread (for example Starlette's
        ``iterate_in_threadpool``) records onto that worker's thread-local and
        leaves this property empty on the request thread. Use a
        ``telemetry_sink`` for anything durable, and always for streaming.
        """
        return tuple(getattr(self._state, "attempts", ()))

    def _begin_operation(self) -> None:
        """Reset attempt telemetry for the calling thread."""
        self._state.attempts = []

    def complete(
        self,
        request: ModelRequest,
        config: ModelConfig,
        *,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Execute a governed completion across ordered model targets.

        Args:
            request: Provider-neutral model request.
            config: Resolved model and recovery policy.
            metadata: Provider-neutral execution correlation metadata.

        Returns:
            Normalized response from the first successful target.

        Raises:
            ModelGatewayError: If preflight, execution, or limits fail closed.
        """
        self._begin_operation()
        prepared = self._preflight(request, config, streaming=False)
        coordinator = _AttemptCoordinator(self, config, prepared)
        for target_index, item in enumerate(prepared):
            if item.capability_error is not None:
                outcome = coordinator.capability_error_outcome(target_index, item)
                if outcome is AttemptOutcome.FALLBACK:
                    continue
                raise item.capability_error

            retries = item.target.retries or 0
            for retry_index in range(retries + 1):
                coordinator.admit_call(item)
                started = time.perf_counter()
                response: ModelResponse | None = None
                succeeded = False
                try:
                    with _model_trace(
                        agent_id=_metadata_agent_id(metadata),
                        provider=item.target.provider or "",
                        model=item.target.name,
                        fallback_attempt=target_index,
                        run_id=_metadata_context(metadata, "run_id"),
                        tenant_id=_metadata_context(metadata, "tenant_id"),
                    ) as model_trace:
                        try:
                            response = item.provider.complete(
                                request, item.target, metadata
                            )
                        except BaseException as exc:
                            model_trace.latency_ms = (
                                time.perf_counter() - started
                            ) * 1000
                            model_trace.error_code = _span_error_code(exc)
                            raise
                        duration_ms = (time.perf_counter() - started) * 1000
                        model_trace.latency_ms = duration_ms
                        model_trace.input_tokens = response.usage.input_tokens
                        model_trace.output_tokens = response.usage.output_tokens
                        model_trace.estimated_cost_usd = response.cost.usd
                        coordinator.account_success(
                            item, duration_ms, response.usage, response.cost
                        )
                        coordinator.enforce_usage_limits(item)
                    succeeded = True
                except Exception as exc:
                    duration_ms = (time.perf_counter() - started) * 1000
                    outcome, error = coordinator.decide_failure(
                        exc,
                        item,
                        target_index,
                        retry_index,
                        retries,
                        duration_ms=duration_ms,
                        usage=response.usage if response is not None else TokenUsage(),
                        cost=response.cost if response is not None else EstimatedCost(),
                    )
                    if outcome is AttemptOutcome.RETRY:
                        coordinator.backoff_before_retry(retry_index)
                        continue
                    if outcome is AttemptOutcome.FALLBACK:
                        break
                    raise error from None
                if succeeded and response is not None:
                    coordinator.record_success(
                        item, duration_ms, response.usage, response.cost
                    )
                    return replace(
                        response,
                        metadata=replace(
                            response.metadata,
                            provider=item.target.provider or "",
                            model=item.target.name,
                            latency_ms=duration_ms,
                        ),
                    )
        raise ModelProviderError(  # pragma: no cover - defensive invariant guard
            "model gateway exhausted configured targets"
        )

    def stream(
        self,
        request: ModelRequest,
        config: ModelConfig,
        *,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Return a governed stream of normalized chunks.

        Args:
            request: Provider-neutral model request.
            config: Resolved model and recovery policy.
            metadata: Provider-neutral execution correlation metadata.

        Returns:
            Iterable of normalized chunks from one successful attempt.
        """
        self._begin_operation()
        prepared = self._preflight(request, config, streaming=True)
        return self._stream_prepared(prepared, request, config, metadata)

    def _stream_prepared(
        self,
        prepared: tuple[PreparedTarget, ...],
        request: ModelRequest,
        config: ModelConfig,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Execute preflighted streaming targets, buffering each attempt atomically.

        The generator body runs on whichever thread drives ``next()``, which is
        not necessarily the thread that called ``stream()``. Resetting here binds
        the attempt list to the consuming thread; without it that thread's list
        is never cleared and grows by one record per stream for the lifetime of
        a pooled worker.
        """
        self._begin_operation()
        coordinator = _AttemptCoordinator(self, config, prepared)
        for target_index, item in enumerate(prepared):
            if item.capability_error is not None:
                outcome = coordinator.capability_error_outcome(target_index, item)
                if outcome is AttemptOutcome.FALLBACK:
                    continue
                raise item.capability_error
            provider = item.provider
            if not isinstance(provider, StreamingModelProvider):
                # Checked before the call budget: a provider that cannot stream
                # never issues a call, so it must not consume one.
                outcome = coordinator.capability_error_outcome(target_index, item)
                if outcome is AttemptOutcome.FALLBACK:
                    continue
                raise ModelUnsupportedCapabilityError(
                    "provider does not implement streaming",
                    provider=item.target.provider,
                    model=item.target.name,
                )
            retries = item.target.retries or 0
            for retry_index in range(retries + 1):
                coordinator.admit_call(item)
                started = time.perf_counter()
                usage = TokenUsage()
                cost = EstimatedCost()
                emitted = False
                recorded = False
                succeeded = False
                try:
                    with _model_trace(
                        agent_id=_metadata_agent_id(metadata),
                        provider=item.target.provider or "",
                        model=item.target.name,
                        fallback_attempt=target_index,
                        set_current=False,
                        run_id=_metadata_context(metadata, "run_id"),
                        tenant_id=_metadata_context(metadata, "tenant_id"),
                    ) as model_trace:
                        try:
                            for chunk in provider.stream(
                                request, item.target, metadata
                            ):
                                if chunk.usage is not None:
                                    usage = chunk.usage
                                if chunk.cost is not None:
                                    cost = chunk.cost
                                if chunk.usage is not None or chunk.cost is not None:
                                    model_trace.input_tokens = usage.input_tokens
                                    model_trace.output_tokens = usage.output_tokens
                                    model_trace.estimated_cost_usd = cost.usd
                                    coordinator.check_projected_usage(item, usage, cost)
                                emitted = True
                                yield chunk
                        except BaseException as exc:
                            model_trace.latency_ms = (
                                time.perf_counter() - started
                            ) * 1000
                            model_trace.error_code = _span_error_code(exc)
                            # Same reasoning as the non-streaming path: usage
                            # reported before the failure was still billed.
                            coordinator.budget.tokens += usage.total_tokens
                            coordinator.budget.cost_usd += cost.usd
                            raise
                        duration_ms = (time.perf_counter() - started) * 1000
                        model_trace.latency_ms = duration_ms
                        model_trace.input_tokens = usage.input_tokens
                        model_trace.output_tokens = usage.output_tokens
                        model_trace.estimated_cost_usd = cost.usd
                        coordinator.account_success(item, duration_ms, usage, cost)
                    succeeded = True
                except Exception as exc:
                    recorded = True
                    outcome, error = coordinator.decide_failure(
                        exc,
                        item,
                        target_index,
                        retry_index,
                        retries,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        usage=usage,
                        cost=cost,
                        mid_stream_emitted=emitted,
                    )
                    if outcome is AttemptOutcome.RETRY:
                        coordinator.backoff_before_retry(retry_index)
                        continue
                    if outcome is AttemptOutcome.FALLBACK:
                        break
                    raise error from None
                finally:
                    if not recorded and not succeeded:
                        # The consumer stopped iterating before the generator
                        # finished -- a client disconnect, or simply `break`
                        # after the terminal chunk, which is the ordinary
                        # streaming idiom. The provider call was made and
                        # billed, so it must not vanish from the governance
                        # record; but no provider error occurred, so it must not
                        # be labelled as one either. Attributing this to
                        # `provider_error` made every ordinary `break` look like
                        # a failure in error-rate telemetry.
                        recorded = True
                        coordinator.record_success(
                            item, (time.perf_counter() - started) * 1000, usage, cost
                        )
                if succeeded:
                    coordinator.record_success(item, duration_ms, usage, cost)
                    return
        raise ModelProviderError(  # pragma: no cover - defensive invariant guard
            "model gateway exhausted configured streaming targets"
        )

    def _preflight(
        self,
        request: ModelRequest,
        config: ModelConfig,
        *,
        streaming: bool,
    ) -> tuple[PreparedTarget, ...]:
        """Resolve every provider and capability before any invocation."""
        if config.provider is None:
            raise ModelProviderNotConfiguredError(
                "model configuration resolved no provider",
                provider="",
                model=config.name,
            )
        if config.fallback and not config.fallback_on:
            raise ModelInvalidRequestError(
                "fallback targets require non-empty fallbackOn"
            )
        targets = (_effective_primary(config),) + tuple(
            _effective_fallback(config, target) for target in config.fallback
        )
        providers = tuple(
            self._registry.resolve(target.provider or "", model=target.name)
            for target in targets
        )
        required = _required_capabilities(request, config, streaming=streaming)
        prepared: list[PreparedTarget] = []
        for target, provider in zip(targets, providers, strict=True):
            capabilities = provider.capabilities(target)
            missing = tuple(
                capability
                for capability in required
                if not capabilities.supports(capability)
            )
            error = None
            if missing:
                error = ModelUnsupportedCapabilityError(
                    f"model target lacks required capabilities: {', '.join(missing)}",
                    provider=target.provider,
                    model=target.name,
                )
            prepared.append(PreparedTarget(target, provider, error))
        first_error = next(
            (item.capability_error for item in prepared if item.capability_error), None
        )
        if (
            first_error is not None
            and "unsupported_capability" not in config.fallback_on
        ):
            raise first_error
        return tuple(prepared)

    def _can_recover(
        self,
        code: ModelErrorCode,
        config: ModelConfig,
        target_index: int,
        prepared: tuple[PreparedTarget, ...],
    ) -> bool:
        """Return whether policy allows advancing to the next target."""
        return code in config.fallback_on and target_index + 1 < len(prepared)

    def _record(self, telemetry: AttemptTelemetry) -> None:
        """Record safe attempt telemetry and notify the optional sink.

        A sink failure is never a provider failure: it is isolated here so it
        cannot discard a paid-for response or trigger a spurious fallback.
        """
        attempts: list[AttemptTelemetry] = getattr(self._state, "attempts", [])
        attempts.append(telemetry)
        self._state.attempts = attempts
        if self._telemetry_sink is None:
            return
        try:
            self._telemetry_sink(telemetry)
        except Exception as exc:  # noqa: BLE001 - telemetry must not break execution
            # Deliberately not `exc_info=True`: this runs inside the gateway's
            # `except` block, so the implicit `__context__` chain would format
            # the raw provider exception -- credentials included -- into the log
            # record, defeating redaction on a second channel.
            logger.warning(
                "model gateway telemetry sink failed for provider=%s model=%s: %s: %s",
                telemetry.provider,
                telemetry.model,
                type(exc).__name__,
                redact_error_message(exc),
            )


def _effective_primary(config: ModelConfig) -> ModelTarget:
    """Copy the resolved primary configuration into a target."""
    return ModelTarget(
        provider=config.provider,
        name=config.name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout_seconds=config.timeout_seconds,
        retries=config.retries,
    )


def _effective_fallback(config: ModelConfig, target: ModelTarget) -> ModelTarget:
    """Apply primary defaults to optional fallback overrides."""
    return ModelTarget(
        provider=target.provider,
        name=target.name,
        temperature=(
            target.temperature if target.temperature is not None else config.temperature
        ),
        max_tokens=(
            target.max_tokens if target.max_tokens is not None else config.max_tokens
        ),
        timeout_seconds=(
            target.timeout_seconds
            if target.timeout_seconds is not None
            else config.timeout_seconds
        ),
        retries=target.retries if target.retries is not None else config.retries,
    )


def _required_capabilities(
    request: ModelRequest,
    config: ModelConfig,
    *,
    streaming: bool,
) -> tuple[ModelCapabilityId, ...]:
    """Combine declared and request-inferred capability requirements."""
    required: list[ModelCapabilityId] = list(config.required_capabilities)
    if request.tools or any(message.tool_calls for message in request.messages):
        required.append("tool_calling")
    if request.structured_output_schema is not None:
        required.append("structured_output")
    if streaming:
        required.append("streaming")
    return tuple(dict.fromkeys(required))


def _check_timeout(duration_ms: float, target: ModelTarget) -> None:
    """Convert an elapsed per-attempt timeout into a typed failure."""
    if (
        target.timeout_seconds is not None
        and duration_ms > target.timeout_seconds * 1000
    ):
        from backend.llm.contracts import ModelTimeoutError

        raise ModelTimeoutError(
            "model attempt exceeded configured timeout",
            provider=target.provider,
            model=target.name,
        )


def _metadata_agent_id(metadata: ExecutionMetadata) -> str:
    """Read safe agent correlation from internal execution metadata."""
    agent_id = metadata.attributes.get("agent_id")
    return agent_id if isinstance(agent_id, str) else ""


def _metadata_context(metadata: ExecutionMetadata, key: str) -> str:
    """Read one safe correlation identifier from execution metadata.

    Args:
        metadata: Provider-neutral execution metadata.
        key: Internal correlation attribute name.

    Returns:
        The string value, or an empty string for absent/non-string values.
    """
    value = metadata.attributes.get(key)
    return value if isinstance(value, str) else ""


__all__ = ["AttemptOutcome", "ModelGateway", "RetryBackoff", "TelemetrySink"]
