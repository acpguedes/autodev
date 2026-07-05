"""Typed Reasoning Strategy contract (E4-S1).

Defines the versioned, SemVer-stable surface a Reasoning Strategy plugin must
implement, and the Reasoning Strategy manifest (``reasoning-strategy.yaml``)
that packages a strategy as a plugin extension at the ``reasoning`` extension
point (:class:`backend.plugins.catalog.ExtensionPointKind.REASONING`).

See ``docs/architecture/v2_platform_reference.md`` §8.3 for the canonical
(pt-BR) specification this module implements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.reasoning.policy import ReasoningPolicy

#: Compatibility range this contract module implements. Bump only on a
#: breaking (MAJOR) change to the dataclasses/Protocols below.
REASONING_CONTRACT_HOST_API = ">=2.0 <3.0"

STRATEGY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ENTRYPOINT_REF_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")

#: Valid values for :attr:`ReasoningOutput.stop_reason`, per reference §8.3.
STOP_REASONS = frozenset({"completed", "budget_exhausted", "guardrail_blocked", "error"})

#: Valid values for :attr:`GuardrailResult.action`, per reference §8.5.
GUARDRAIL_ACTIONS = frozenset({"block", "repair_once", "warn"})


class ReasoningError(RuntimeError):
    """Base class for errors raised by the Reasoning Engine mediator."""


class BudgetExceededError(ReasoningError):
    """Raised when a reasoning run would exceed its configured :class:`Budget`.

    The Reasoning Engine fails closed on this error: no further external
    effect (LLM call, tool call) is performed once it is raised.

    Attributes:
        usage: The :class:`Usage` accumulated up to (and including) the point
            the budget was exceeded.
    """

    def __init__(self, message: str, usage: "Usage") -> None:
        """Initialize the error with the usage snapshot that triggered it.

        Args:
            message: Human-readable description of the violation.
            usage: Usage accumulated at the moment the budget was exceeded.
        """
        super().__init__(message)
        self.usage = usage


class GuardrailBlockedError(ReasoningError):
    """Raised when a strategy itself determines its output must be blocked.

    Strategies are not required to raise this directly — the common path is
    to return normally and let :meth:`ReasoningContext.verify` (invoked by the
    Reasoning Engine after ``run()`` returns) evaluate guardrails. This
    exception exists for strategies that can detect a hard violation mid-run
    and want to short-circuit immediately.

    Attributes:
        result: The failing :class:`GuardrailResult` that triggered the block.
        usage: The :class:`Usage` accumulated at the point of the block.
    """

    def __init__(self, message: str, result: "GuardrailResult", usage: "Usage") -> None:
        """Initialize the error with the failing result and usage snapshot.

        Args:
            message: Human-readable description of the violation.
            result: The guardrail result that caused the block.
            usage: Usage accumulated at the moment of the block.
        """
        super().__init__(message)
        self.result = result
        self.usage = usage


@dataclass(frozen=True)
class Budget:
    """Resource ceiling enforced by the Reasoning Engine for a single run.

    Attributes:
        tokens: Maximum total tokens (prompt + completion) allowed.
        cost_usd: Maximum cost in US dollars allowed.
        wall_clock_ms: Maximum wall-clock duration allowed, in milliseconds.
        max_steps: Maximum number of mediated calls (``call_llm``/``call_tool``)
            allowed.
    """

    tokens: int
    cost_usd: float
    wall_clock_ms: int
    max_steps: int


@dataclass(frozen=True)
class Usage:
    """Resources consumed so far in a reasoning run.

    Immutable accumulator: use :meth:`accumulate` to obtain an updated copy
    rather than mutating in place, so a `Usage` snapshot attached to an
    exception or trace event never changes retroactively.

    Attributes:
        tokens: Total tokens consumed so far.
        cost_usd: Total cost in US dollars consumed so far.
        wall_clock_ms: Total wall-clock time consumed so far, in milliseconds.
        steps: Number of mediated calls performed so far.
    """

    tokens: int = 0
    cost_usd: float = 0.0
    wall_clock_ms: int = 0
    steps: int = 0

    def accumulate(
        self,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        wall_clock_ms: int = 0,
        steps: int = 0,
    ) -> "Usage":
        """Return a new :class:`Usage` with the given deltas added.

        Args:
            tokens: Tokens to add.
            cost_usd: Cost in US dollars to add.
            wall_clock_ms: Wall-clock milliseconds to add.
            steps: Steps to add.

        Returns:
            A new `Usage` instance; `self` is left unchanged.
        """
        return replace(
            self,
            tokens=self.tokens + tokens,
            cost_usd=self.cost_usd + cost_usd,
            wall_clock_ms=self.wall_clock_ms + wall_clock_ms,
            steps=self.steps + steps,
        )

    def exceeds(self, budget: "Budget") -> bool:
        """Check whether this usage has crossed any dimension of `budget`.

        ``steps`` is checked with a reached-or-exceeded (``>=``) comparison
        because the cost of one more step (in step-count terms) is known
        before the step is attempted, so the engine can refuse the step that
        would push the run over the ceiling. ``tokens``, ``cost_usd``, and
        ``wall_clock_ms`` are checked with a strict (``>``) comparison because
        the cost of a single call is not known until it returns; the call
        that crosses the ceiling is allowed to finish and the *next* one is
        refused. Both are fail-closed: no dimension can be exceeded twice.

        Args:
            budget: The budget to check against.

        Returns:
            ``True`` if any dimension has been reached or exceeded.
        """
        return (
            self.steps >= budget.max_steps
            or self.tokens > budget.tokens
            or self.cost_usd > budget.cost_usd
            or self.wall_clock_ms > budget.wall_clock_ms
        )


@dataclass(frozen=True)
class ToolSpec:
    """A tool or skill made available to a reasoning strategy.

    Attributes:
        name: Identifier the strategy passes to :meth:`ReasoningContext.call_tool`.
        description: Human-readable description of what the tool does.
        parameters_schema: JSON Schema describing the tool's call arguments.
    """

    name: str
    description: str = ""
    parameters_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceEvent:
    """A single ordered step in a reasoning run's trace.

    Attributes:
        sequence: Monotonically increasing position of this event in the run.
        name: Dotted event name (``domain.entity.action``), e.g.
            ``"reasoning.step.thought"`` or ``"reasoning.tool.called"``.
        payload: Event-specific structured data.
        timestamp: Unix timestamp (seconds) the event was emitted at.
    """

    sequence: int
    name: str
    payload: dict[str, Any]
    timestamp: float


@dataclass(frozen=True)
class GuardrailResult:
    """Outcome of evaluating a single guardrail against a candidate output.

    Attributes:
        guardrail_id: Identifier of the evaluated guardrail, or ``""`` for the
            synthetic "all guardrails passed" result.
        passed: Whether the output satisfied the guardrail.
        action: One of :data:`GUARDRAIL_ACTIONS`; only meaningful when
            ``passed`` is ``False``.
        message: Human-readable explanation of the violation, if any.
    """

    guardrail_id: str
    passed: bool
    action: str = ""
    message: str = ""


@dataclass(frozen=True)
class LLMResult:
    """Outcome of a single mediated LLM call.

    Attributes:
        content: The provider's response payload.
        tokens_input: Prompt tokens consumed by this call.
        tokens_output: Completion tokens consumed by this call.
        cost_usd: Cost in US dollars of this call.
    """

    content: Any
    tokens_input: int
    tokens_output: int
    cost_usd: float


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a single mediated tool call.

    Attributes:
        name: Identifier of the tool that was called.
        output: The tool's return value.
        cost_usd: Cost in US dollars attributed to this call, if any.
        tokens: Tokens attributed to this call, if any (e.g. for tools that
            themselves invoke an LLM).
    """

    name: str
    output: Any
    cost_usd: float = 0.0
    tokens: int = 0


@dataclass(frozen=True)
class ReasoningInput:
    """Immutable context handed to a :class:`ReasoningStrategy` for one run.

    Attributes:
        task: Description of the task/objective to reason about.
        messages: Session history (role-tagged messages).
        tools: Tools/skills available to the strategy for this run.
        policy: The declarative :class:`~backend.reasoning.policy.ReasoningPolicy`
            in effect (guardrails, budget, tracing, selection).
        budget: Resource ceiling for this run.
        seed: Optional seed for deterministic replay.
    """

    task: str
    messages: Sequence[dict[str, Any]]
    tools: Sequence[ToolSpec]
    policy: ReasoningPolicy
    budget: Budget
    seed: int | None = None


@dataclass(frozen=True)
class ReasoningOutput:
    """Final, structured result of a reasoning run.

    Attributes:
        content: The strategy's final answer (text or structured payload).
        stop_reason: One of :data:`STOP_REASONS`.
        usage: Total resources consumed by the run.
        trace_id: Anchor identifier for the run's trace (replay/audit).
    """

    content: Any
    stop_reason: str
    usage: Usage
    trace_id: str


class ReasoningContext(Protocol):
    """Mediator of side effects: the single path for LLM/tool calls and traces.

    Every :class:`ReasoningStrategy` implementation receives an instance of
    this protocol and MUST route all external effects through it. Each call
    debits the run's :class:`Budget` and is recorded in the ordered trace.
    Strategies never call an LLM provider or tool directly.
    """

    async def call_llm(self, messages: Sequence[dict[str, Any]], **opts: Any) -> LLMResult:
        """Invoke the LLM provider, mediated for budget and trace enforcement.

        Args:
            messages: Role-tagged messages to send to the provider.
            **opts: Provider-specific call options.

        Returns:
            The provider's result, with token/cost accounting.

        Raises:
            BudgetExceededError: If the run's budget has been reached or
                exceeded; the call is not made when this is raised.
        """
        ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Invoke a tool/skill, mediated for budget and trace enforcement.

        Args:
            name: Identifier of the tool to call, from the run's ``tools``.
            args: Arguments to pass to the tool.

        Returns:
            The tool's result, with token/cost accounting.

        Raises:
            BudgetExceededError: If the run's budget has been reached or
                exceeded; the call is not made when this is raised.
        """
        ...

    async def check_budget(self) -> None:
        """Raise if the run's accumulated usage has reached its budget.

        Strategies should call this before any costly step so they can stop
        gracefully; the mediator also calls it internally before every
        ``call_llm``/``call_tool`` as a defense-in-depth fail-closed guarantee.

        Raises:
            BudgetExceededError: If any budget dimension has been reached or
                exceeded.
        """
        ...

    async def verify(self, output: Any) -> GuardrailResult:
        """Evaluate the run's guardrails against a candidate output.

        Args:
            output: Candidate final output to verify.

        Returns:
            The first failing :class:`GuardrailResult`, or a synthetic
            passing result if every guardrail passed.
        """
        ...

    def emit(self, event: TraceEvent) -> None:
        """Record an ordered reasoning step in the run's trace.

        Args:
            event: The trace event to record.
        """
        ...


class ReasoningStrategy(Protocol):
    """Pluggable reasoning strategy contract (extension point ``reasoning``).

    Attributes:
        id: Fully qualified strategy id, e.g. ``"autodev/reasoning-react"``.
        version: SemVer version of this strategy implementation.
        host_api: Compatibility range this strategy supports, e.g.
            ``">=2.0 <3.0"``.
    """

    id: str
    version: str
    host_api: str

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema describing this strategy's configuration.

        Returns:
            A JSON Schema object.
        """
        ...

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Execute one full reasoning run and return its final output.

        Implementations must: (1) route every external effect through `ctx`;
        (2) be stateless between runs — state lives in the trace/run state,
        not on the strategy instance; (3) call ``ctx.check_budget()`` before
        each costly step; (4) pass the final output through ``ctx.verify()``
        before returning (the Reasoning Engine also verifies independently as
        a fail-closed boundary, but a well-behaved strategy verifies first so
        it can react to a ``repair_once`` guardrail within its own run).

        Streaming note: intermediate reasoning steps are streamed in real
        time via ``ctx.emit()`` (reference §8.6) — that is the observability
        channel for a running strategy. ``run()`` itself always resolves to
        the final :class:`ReasoningOutput`; it does not itself need to be an
        async generator. The reference contract's pseudocode return type
        (``AsyncIterator[TraceEvent] | ReasoningOutput``) is preserved as
        :data:`ReasoningStrategyResult` for forward compatibility with a
        fully-streaming return path, which is not implemented in E4-S1 —
        :class:`~backend.reasoning.engine.ReasoningEngine` defensively drains
        an async-iterator return value if a strategy produces one, but the
        primary, fully-tested path is the coroutine-returning one above.

        Args:
            input: Immutable context for this run.
            ctx: Mediator for all LLM/tool calls, budget checks, guardrail
                verification, and trace emission.

        Returns:
            The run's final, structured result.
        """
        ...


#: Forward-compatible alias documenting the reference contract's return-type
#: union (see :meth:`ReasoningStrategy.run`'s docstring). Not used as the
#: concrete return annotation in E4-S1.
ReasoningStrategyResult = "ReasoningOutput | AsyncIterator[TraceEvent]"


@dataclass(frozen=True)
class ReasoningEntrypoint:
    """Reference to the callable that implements a reasoning strategy.

    Attributes:
        runtime: Runtime used to execute the entrypoint, e.g. ``"python"``.
        ref: Module and callable reference, e.g. ``"pkg.module:Strategy"``.
    """

    runtime: str
    ref: str


@dataclass(frozen=True)
class ReasoningStrategyManifest:
    """Fully parsed and validated ``reasoning-strategy.yaml`` manifest.

    Attributes:
        schema_version: Manifest schema version.
        kind: Manifest kind, always ``"ReasoningStrategy"``.
        id: Fully qualified strategy id in ``namespace/name`` format.
        version: SemVer version of the strategy.
        host_api: Supported host API version range.
        entrypoint: Reference to the strategy's implementation.
        display_name: Optional human-readable name.
        description: Optional human-readable description.
        raw: Original parsed manifest document.
    """

    schema_version: str
    kind: str
    id: str
    version: str
    host_api: str
    entrypoint: ReasoningEntrypoint
    display_name: str | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningStrategyValidationResult:
    """Outcome of validating a raw reasoning strategy manifest document.

    Attributes:
        valid: Whether the manifest passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        manifest: The parsed manifest, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    manifest: ReasoningStrategyManifest | None = None


def validate_reasoning_strategy_manifest(raw: dict[str, Any]) -> ReasoningStrategyValidationResult:
    """Validate a raw manifest document and parse it into a manifest object.

    Args:
        raw: Parsed ``reasoning-strategy.yaml`` document, keyed by camelCase
            field names.

    Returns:
        A result indicating whether the manifest is valid; on success it
        carries the parsed :class:`ReasoningStrategyManifest`, on failure the
        list of error messages.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "kind", "id", "version", "hostApi", "entrypoint"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion"))
    kind = _string(raw.get("kind"))
    strategy_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))

    if kind and kind != "ReasoningStrategy":
        errors.append("kind must be ReasoningStrategy")
    if strategy_id and not STRATEGY_ID_RE.match(strategy_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    entrypoint = _parse_entrypoint(raw.get("entrypoint"), errors)

    if errors:
        return ReasoningStrategyValidationResult(False, errors)

    return ReasoningStrategyValidationResult(
        True,
        [],
        ReasoningStrategyManifest(
            schema_version=schema_version,
            kind=kind,
            id=strategy_id,
            version=version,
            host_api=host_api,
            entrypoint=entrypoint,
            display_name=_string(raw.get("displayName")) or None,
            description=_string(raw.get("description")) or None,
            raw=dict(raw),
        ),
    )


def load_reasoning_strategy_manifest(path: Path | str) -> ReasoningStrategyManifest:
    """Load, parse, and validate a ``reasoning-strategy.yaml`` manifest from disk.

    Args:
        path: Path to the ``reasoning-strategy.yaml`` file.

    Returns:
        The parsed and validated :class:`ReasoningStrategyManifest`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("reasoning-strategy.yaml must contain a mapping at the document root")
    result = validate_reasoning_strategy_manifest(raw)
    if not result.valid or result.manifest is None:
        raise ValueError("; ".join(result.errors))
    return result.manifest


def _parse_entrypoint(raw: Any, errors: list[str]) -> ReasoningEntrypoint:
    """Parse and validate the ``entrypoint`` section of a raw manifest.

    Args:
        raw: Raw value of the ``entrypoint`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed entrypoint; empty fields if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("entrypoint must be an object")
        return ReasoningEntrypoint("", "")
    runtime = _string(raw.get("runtime"))
    ref = _string(raw.get("ref"))
    if runtime != "python":
        errors.append("entrypoint.runtime must be python")
    if not ref or not ENTRYPOINT_REF_RE.match(ref):
        errors.append("entrypoint.ref must use module:callable format")
    return ReasoningEntrypoint(runtime, ref)


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``str``, otherwise an empty string.
    """
    return value if isinstance(value, str) else ""


def _is_semver(value: str) -> bool:
    """Check whether a string is a valid ``MAJOR.MINOR.PATCH`` SemVer version.

    Args:
        value: Candidate version string.

    Returns:
        ``True`` if ``value`` is a valid SemVer version, ``False`` otherwise.
    """
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _is_supported_range(value: str) -> bool:
    """Check whether a string is a valid version range expression.

    Args:
        value: Candidate range expression, or ``"*"`` for any version.

    Returns:
        ``True`` if ``value`` is ``"*"`` or a valid, non-empty specifier set.
    """
    if value == "*":
        return True
    try:
        SpecifierSet(value.replace(" ", ","))
    except InvalidSpecifier:
        return False
    return bool(value.strip())


__all__ = [
    "BudgetExceededError",
    "Budget",
    "ENTRYPOINT_REF_RE",
    "GUARDRAIL_ACTIONS",
    "GuardrailBlockedError",
    "GuardrailResult",
    "LLMResult",
    "REASONING_CONTRACT_HOST_API",
    "ReasoningContext",
    "ReasoningEntrypoint",
    "ReasoningError",
    "ReasoningInput",
    "ReasoningOutput",
    "ReasoningStrategy",
    "ReasoningStrategyManifest",
    "ReasoningStrategyResult",
    "ReasoningStrategyValidationResult",
    "STOP_REASONS",
    "STRATEGY_ID_RE",
    "SEMVER_RE",
    "ToolResult",
    "ToolSpec",
    "TraceEvent",
    "Usage",
    "load_reasoning_strategy_manifest",
    "validate_reasoning_strategy_manifest",
]
