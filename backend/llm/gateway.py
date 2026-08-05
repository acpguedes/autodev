"""Governed provider-neutral model gateway execution."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
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
    ModelInvalidRequestError,
    ModelProviderError,
    ModelProviderNotConfiguredError,
    ModelUnsupportedCapabilityError,
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
    ) as measurements:
        yield measurements


def _span_error_code(error: BaseException) -> str:
    """Return this error's own code for span annotation.

    The value is a hint, not a guarantee: ``trace_model_call`` clamps whatever
    lands here to the stable vocabulary, so a vendor code such as
    ``invalid_api_key`` cannot reach a span even though it is returned here.
    """
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else "provider_error"


class ModelGateway:
    """Apply capability, retry, fallback, limit, and telemetry policy."""

    def __init__(
        self,
        registry: ModelProviderRegistry,
        *,
        telemetry_sink: TelemetrySink | None = None,
    ) -> None:
        """Initialize the gateway.

        Args:
            registry: Provider registry used for every target.
            telemetry_sink: Optional callback receiving safe attempt telemetry.
        """
        self._registry = registry
        self._telemetry_sink = telemetry_sink
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
        budget = GatewayBudget()
        attempt_number = 0
        for target_index, item in enumerate(prepared):
            if item.capability_error is not None:
                attempt_number += 1
                self._record(
                    AttemptTelemetry(
                        attempt=attempt_number,
                        provider=item.target.provider or "",
                        model=item.target.name,
                        duration_ms=0.0,
                        error_code="unsupported_capability",
                    )
                )
                if self._can_recover(
                    "unsupported_capability", config, target_index, prepared
                ):
                    continue
                raise item.capability_error

            retries = item.target.retries or 0
            for retry_index in range(retries + 1):
                check_call_limit(config.limits, budget, item.target)
                budget.calls += 1
                attempt_number += 1
                started = time.perf_counter()
                response: ModelResponse | None = None
                succeeded = False
                try:
                    with _model_trace(
                        agent_id=_metadata_agent_id(metadata),
                        provider=item.target.provider or "",
                        model=item.target.name,
                        fallback_attempt=target_index,
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
                        # Account the attempt before enforcing ceilings: a slow
                        # or over-budget attempt was still billed by the
                        # provider, so it must not be free to the budget.
                        budget.tokens += response.usage.total_tokens
                        budget.cost_usd += response.cost.usd
                        _check_timeout(duration_ms, item.target)
                        check_usage_limits(config.limits, budget, item.target)
                    succeeded = True
                except Exception as exc:
                    error = redacted_gateway_error(
                        exc,
                        provider=item.target.provider or "",
                        model=item.target.name,
                    )
                    duration_ms = (time.perf_counter() - started) * 1000
                    self._record(
                        AttemptTelemetry(
                            attempt=attempt_number,
                            provider=item.target.provider or "",
                            model=item.target.name,
                            duration_ms=duration_ms,
                            usage=(
                                response.usage if response is not None else TokenUsage()
                            ),
                            cost=(
                                response.cost
                                if response is not None
                                else EstimatedCost()
                            ),
                            error_code=error.code,
                        )
                    )
                    if isinstance(error, ModelBudgetExceededError):
                        raise error from exc
                    if error.code in config.fallback_on and retry_index < retries:
                        continue
                    if self._can_recover(error.code, config, target_index, prepared):
                        break
                    raise error from exc
                if succeeded and response is not None:
                    self._record(
                        AttemptTelemetry(
                            attempt=attempt_number,
                            provider=item.target.provider or "",
                            model=item.target.name,
                            duration_ms=duration_ms,
                            usage=response.usage,
                            cost=response.cost,
                        )
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
        """Execute preflighted streaming targets, buffering each attempt atomically."""
        budget = GatewayBudget()
        attempt_number = 0
        for target_index, item in enumerate(prepared):
            if item.capability_error is not None:
                attempt_number += 1
                self._record(
                    AttemptTelemetry(
                        attempt_number,
                        item.target.provider or "",
                        item.target.name,
                        0.0,
                        error_code="unsupported_capability",
                    )
                )
                if self._can_recover(
                    "unsupported_capability", config, target_index, prepared
                ):
                    continue
                raise item.capability_error
            provider = item.provider
            if not isinstance(provider, StreamingModelProvider):
                # Checked before the call budget: a provider that cannot stream
                # never issues a call, so it must not consume one.
                attempt_number += 1
                self._record(
                    AttemptTelemetry(
                        attempt_number,
                        item.target.provider or "",
                        item.target.name,
                        0.0,
                        error_code="unsupported_capability",
                    )
                )
                if self._can_recover(
                    "unsupported_capability", config, target_index, prepared
                ):
                    continue
                raise ModelUnsupportedCapabilityError(
                    "provider does not implement streaming",
                    provider=item.target.provider,
                    model=item.target.name,
                )
            retries = item.target.retries or 0
            for retry_index in range(retries + 1):
                check_call_limit(config.limits, budget, item.target)
                budget.calls += 1
                attempt_number += 1
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
                                    projected = GatewayBudget(
                                        calls=budget.calls,
                                        tokens=budget.tokens + usage.total_tokens,
                                        cost_usd=budget.cost_usd + cost.usd,
                                    )
                                    check_usage_limits(
                                        config.limits, projected, item.target
                                    )
                                emitted = True
                                yield chunk
                        except BaseException as exc:
                            model_trace.latency_ms = (
                                time.perf_counter() - started
                            ) * 1000
                            model_trace.error_code = _span_error_code(exc)
                            # Same reasoning as the non-streaming path: usage
                            # reported before the failure was still billed.
                            budget.tokens += usage.total_tokens
                            budget.cost_usd += cost.usd
                            raise
                        duration_ms = (time.perf_counter() - started) * 1000
                        model_trace.latency_ms = duration_ms
                        model_trace.input_tokens = usage.input_tokens
                        model_trace.output_tokens = usage.output_tokens
                        model_trace.estimated_cost_usd = cost.usd
                        budget.tokens += usage.total_tokens
                        budget.cost_usd += cost.usd
                        _check_timeout(duration_ms, item.target)
                    succeeded = True
                except Exception as exc:
                    error = redacted_gateway_error(
                        exc,
                        provider=item.target.provider or "",
                        model=item.target.name,
                    )
                    recorded = True
                    self._record(
                        AttemptTelemetry(
                            attempt_number,
                            item.target.provider or "",
                            item.target.name,
                            (time.perf_counter() - started) * 1000,
                            usage=usage,
                            cost=cost,
                            error_code=error.code,
                        )
                    )
                    if isinstance(error, ModelBudgetExceededError):
                        raise error from exc
                    if emitted:
                        raise error from exc
                    if error.code in config.fallback_on and retry_index < retries:
                        continue
                    if self._can_recover(error.code, config, target_index, prepared):
                        break
                    raise error from exc
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
                        self._record(
                            AttemptTelemetry(
                                attempt_number,
                                item.target.provider or "",
                                item.target.name,
                                (time.perf_counter() - started) * 1000,
                                usage=usage,
                                cost=cost,
                            )
                        )
                if succeeded:
                    self._record(
                        AttemptTelemetry(
                            attempt_number,
                            item.target.provider or "",
                            item.target.name,
                            duration_ms,
                            usage=usage,
                            cost=cost,
                        )
                    )
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
        except Exception:  # noqa: BLE001 - telemetry must not break execution
            logger.warning(
                "model gateway telemetry sink failed for provider=%s model=%s",
                telemetry.provider,
                telemetry.model,
                exc_info=True,
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


__all__ = ["ModelGateway", "TelemetrySink"]
