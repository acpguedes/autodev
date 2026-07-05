"""Typed model and versioning helpers for ``flow.yaml`` manifests.

Dataclasses, canonical vocabularies, and SemVer-range helpers shared by the
parser (:mod:`backend.flows.manifest`), the graph validator
(:mod:`backend.flows.graph`), and the Orchestration Engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

FLOW_SCHEMA_VERSION = "1"
FLOW_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
NODE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

FLOW_NODE_TYPES = frozenset(
    {"agent", "skill", "tool", "conditional", "human", "subflow", "map"}
)
REF_NODE_TYPES = frozenset({"agent", "skill", "tool", "subflow", "map"})
TRIGGER_TYPES = frozenset({"message", "webhook", "cron", "event"})
BACKOFF_MODES = frozenset({"fixed", "exponential"})
REDUCE_MODES = frozenset({"collect"})


@dataclass(frozen=True)
class FlowRetryPolicy:
    """Retry policy applied to a node activation.

    Attributes:
        max_attempts: Total attempts allowed, including the first one.
            Defaults to 1 — retries are opt-in, because re-firing a node
            re-fires its side effects (agent/tool calls are not idempotent).
        backoff: Delay growth mode between attempts, ``"fixed"`` or
            ``"exponential"``.
        initial_delay_sec: Delay before the second attempt, in seconds.
    """

    max_attempts: int = 1
    backoff: str = "exponential"
    initial_delay_sec: float = 2.0


DEFAULT_FLOW_RETRIES = FlowRetryPolicy()


@dataclass(frozen=True)
class FlowDefaults:
    """Node defaults applied when a node does not override them.

    Attributes:
        retries: Default retry policy for every node.
        timeout_sec: Default timeout per node activation, in seconds.
    """

    retries: FlowRetryPolicy = DEFAULT_FLOW_RETRIES
    timeout_sec: int | None = None


@dataclass(frozen=True)
class FlowBudgets:
    """Fail-closed resource limits for a whole flow run.

    Attributes:
        max_cost_usd: Maximum total cost in US dollars.
        max_wall_clock_sec: Maximum wall-clock duration, in seconds.
        max_tokens: Maximum total LLM tokens across all steps.
    """

    max_cost_usd: float = 10.0
    max_wall_clock_sec: int = 3600
    max_tokens: int = 2_000_000

    def violation(
        self, metrics: dict[str, Any], elapsed_sec: float
    ) -> str | None:
        """Check accumulated run metrics against these budgets.

        Args:
            metrics: Run metrics carrying ``tokens`` and ``cost_usd``.
            elapsed_sec: Wall-clock seconds of the current execution session.

        Returns:
            A human-readable violation, or ``None`` when within budget.
        """
        if elapsed_sec > self.max_wall_clock_sec:
            return (
                f"wall clock {elapsed_sec:.1f}s exceeded budget "
                f"{self.max_wall_clock_sec}s"
            )
        if float(metrics.get("tokens", 0.0)) > self.max_tokens:
            return (
                f"tokens {metrics.get('tokens')} exceeded budget {self.max_tokens}"
            )
        if float(metrics.get("cost_usd", 0.0)) > self.max_cost_usd:
            return (
                f"cost {metrics.get('cost_usd')} exceeded budget "
                f"{self.max_cost_usd} USD"
            )
        return None


DEFAULT_FLOW_BUDGETS = FlowBudgets()


@dataclass(frozen=True)
class FlowTrigger:
    """A declaration of what starts the flow.

    Attributes:
        type: Trigger kind: ``message``, ``webhook``, ``cron``, or ``event``.
        on: Event name for ``event`` triggers (``domain.entity.action``).
        schedule: Cron expression for ``cron`` triggers.
        metadata: Additional trigger-specific configuration.
    """

    type: str
    on: str | None = None
    schedule: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowNodeRef:
    """A reference to an executable artifact with an optional version range.

    Attributes:
        id: Artifact identifier in ``namespace/name`` format.
        version_range: SemVer version or range (e.g. ``">=1.0 <2.0"``), or
            ``"*"`` when unconstrained.
    """

    id: str
    version_range: str = "*"

    @property
    def raw(self) -> str:
        """Return the manifest form ``id@range`` of this reference."""
        if self.version_range == "*":
            return self.id
        return f"{self.id}@{self.version_range}"


@dataclass(frozen=True)
class FlowNode:
    """A single node of the flow graph.

    Attributes:
        id: Node identifier, unique within the flow, kebab-case.
        type: Node type, one of :data:`FLOW_NODE_TYPES`.
        ref: Referenced artifact for agent/skill/tool/subflow/map nodes.
        input_bindings: Input bindings; values may embed ``{{ ... }}`` templates.
        prompt: Human-readable prompt, required for ``human`` nodes.
        form: JSON Schema describing the human decision payload.
        timeout_sec: Node activation timeout override, in seconds.
        on_timeout: Node id to route to when a ``human`` node times out.
        retries: Retry policy override for this node.
        over: Template expression yielding the collection a ``map`` node fans
            out over.
        reduce: Aggregation mode for ``map`` nodes.
        max_parallel: Maximum parallel branches for ``map`` nodes.
        raw: Original manifest document for this node.
    """

    id: str
    type: str
    ref: FlowNodeRef | None = None
    input_bindings: dict[str, Any] = field(default_factory=dict)
    prompt: str | None = None
    form: dict[str, Any] | None = None
    timeout_sec: int | None = None
    on_timeout: str | None = None
    retries: FlowRetryPolicy | None = None
    over: str | None = None
    reduce: str = "collect"
    max_parallel: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowEdge:
    """A transition between two nodes.

    Attributes:
        source: Id of the node the edge leaves.
        target: Id of the node the edge enters.
        when: Predicate expression guarding the edge, if conditional.
        on: Named routing signal guarding the edge (e.g. ``"timeout"``).
    """

    source: str
    target: str
    when: str | None = None
    on: str | None = None

    @property
    def guarded(self) -> bool:
        """Whether the edge is taken only when a guard matches."""
        return self.when is not None or self.on is not None


@dataclass(frozen=True)
class FlowIO:
    """Declared input or output schema of a flow.

    Attributes:
        schema_version: Version of the embedded schema document.
        schema: JSON Schema describing the payload.
    """

    schema_version: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class FlowManifest:
    """A parsed, validated ``flow.yaml`` document.

    Attributes:
        schema_version: Flow manifest schema version.
        id: Flow identifier in ``namespace/name`` format.
        version: Flow SemVer version.
        host_api: Host API compatibility range.
        name: Display name.
        description: Human-readable description.
        triggers: Declared run triggers.
        input: Declared run input schema, if any.
        output: Declared run output schema, if any.
        defaults: Node defaults.
        nodes: Flow nodes, in declaration order.
        edges: Flow edges, in declaration order.
        budgets: Fail-closed run budgets.
        raw: Original manifest document.
    """

    schema_version: str
    id: str
    version: str
    host_api: str
    name: str | None = None
    description: str | None = None
    triggers: tuple[FlowTrigger, ...] = ()
    input: FlowIO | None = None
    output: FlowIO | None = None
    defaults: FlowDefaults = FlowDefaults()
    nodes: tuple[FlowNode, ...] = ()
    edges: tuple[FlowEdge, ...] = ()
    budgets: FlowBudgets = DEFAULT_FLOW_BUDGETS
    raw: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: str) -> FlowNode:
        """Return the node with the given id.

        Args:
            node_id: Id of the node to look up.

        Returns:
            The matching :class:`FlowNode`.

        Raises:
            KeyError: If no node has that id.
        """
        for candidate in self.nodes:
            if candidate.id == node_id:
                return candidate
        raise KeyError(node_id)

    def edges_from(self, node_id: str) -> tuple[FlowEdge, ...]:
        """Return every edge leaving the given node, in declaration order.

        Args:
            node_id: Id of the source node.

        Returns:
            The outgoing edges.
        """
        return tuple(edge for edge in self.edges if edge.source == node_id)

    def entry_node(self) -> FlowNode:
        """Return the flow's entry node (the single node with no incoming edge).

        Returns:
            The entry :class:`FlowNode`.

        Raises:
            ValueError: If the graph does not have exactly one entry node.
        """
        targets = {edge.target for edge in self.edges}
        entries = [node for node in self.nodes if node.id not in targets]
        if len(entries) != 1:
            raise ValueError("flow does not have exactly one entry node")
        return entries[0]


@dataclass(frozen=True)
class FlowManifestValidationResult:
    """Outcome of validating a raw flow manifest document.

    Attributes:
        valid: Whether the manifest passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        manifest: The parsed manifest, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    manifest: FlowManifest | None = None


def _is_semver(value: str) -> bool:
    """Whether ``value`` is a SemVer ``MAJOR.MINOR.PATCH`` version."""
    return bool(SEMVER_RE.match(value))


def _is_supported_range(value: str) -> bool:
    """Whether ``value`` is a usable version range or exact version."""
    if value == "*":
        return True
    if _is_semver(value):
        return True
    normalized = ",".join(part for part in value.split() if part)
    try:
        SpecifierSet(normalized)
    except InvalidSpecifier:
        return False
    return True


def version_in_range(version: str, version_range: str) -> bool:
    """Check a SemVer version against a manifest version range.

    Args:
        version: Concrete SemVer version, e.g. ``"1.2.3"``.
        version_range: Exact version, space-separated range expression
            (e.g. ``">=1.0 <2.0"``), or ``"*"``.

    Returns:
        ``True`` when the version satisfies the range.
    """
    if version_range == "*":
        return True
    try:
        parsed = Version(version)
    except InvalidVersion:
        return False
    if _is_semver(version_range):
        return Version(version_range) == parsed
    normalized = ",".join(part for part in version_range.split() if part)
    try:
        return parsed in SpecifierSet(normalized, prereleases=True)
    except InvalidSpecifier:
        return False


__all__ = [
    "BACKOFF_MODES",
    "DEFAULT_FLOW_BUDGETS",
    "DEFAULT_FLOW_RETRIES",
    "FLOW_ID_RE",
    "FLOW_NODE_TYPES",
    "FLOW_SCHEMA_VERSION",
    "FlowBudgets",
    "FlowDefaults",
    "FlowEdge",
    "FlowIO",
    "FlowManifest",
    "FlowManifestValidationResult",
    "FlowNode",
    "FlowNodeRef",
    "FlowRetryPolicy",
    "FlowTrigger",
    "NODE_ID_RE",
    "REDUCE_MODES",
    "REF_NODE_TYPES",
    "SEMVER_RE",
    "TRIGGER_TYPES",
    "version_in_range",
]
