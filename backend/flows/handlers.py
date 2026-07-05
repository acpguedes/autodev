"""Node handler registry and built-in node handlers for the Flow Engine.

Each flow node type maps to a :class:`NodeHandler` that turns a rendered node
input into an output document. Handlers are pluggable so later stories (human
nodes in E3-S4, composite nodes in E3-S5) and plugins can extend execution
without modifying the engine loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from backend.agents.registry_v2 import AgentRegistry
from backend.agents.runtime import AgentRuntime
from backend.flows.model import FlowManifest, FlowNode
from backend.plugins.store import PluginStore


class FlowNodeError(RuntimeError):
    """Raised when a node activation fails."""


class UnsupportedNodeError(FlowNodeError):
    """Raised when no handler supports the node's type (fails closed)."""


class FlowBudgetExceededError(FlowNodeError):
    """Raised when a node breaches the run's remaining budget (fails closed).

    The engine maps this to the ``budget_exhausted`` stop reason; composite
    handlers (E3-S5) raise it when aggregate child consumption exceeds the
    parent's remaining budget or a capped child stops on budget exhaustion.
    """


@dataclass
class NodeContext:
    """Everything a node handler needs to execute one activation.

    Attributes:
        manifest: The flow definition being executed.
        node: The node being activated.
        run_id: Id of the enclosing run.
        tenant_id: Tenant the run is scoped to.
        input: Rendered input bindings for this activation.
        state: The run's mutable state document (read-only by convention).
        services: Engine-provided services keyed by name (e.g. ``"engine"``),
            used by composite handlers.
    """

    manifest: FlowManifest
    node: FlowNode
    run_id: str
    tenant_id: str
    input: dict[str, Any]
    state: dict[str, Any]
    services: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeOutcome:
    """Result of a node activation.

    Attributes:
        output: Output document recorded under ``nodes.<id>.output``.
        metrics: Resource usage to charge against the run budgets
            (keys: ``tokens``, ``cost_usd``).
        status: Terminal step status; ``"completed"`` for normal outcomes.
    """

    output: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)
    status: str = "completed"


class NodeHandler(Protocol):
    """Structural interface for node handlers."""

    def __call__(self, ctx: NodeContext) -> NodeOutcome:
        """Execute one node activation.

        Args:
            ctx: Activation context.

        Returns:
            The activation outcome.

        Raises:
            FlowNodeError: When the activation fails.
        """
        ...


class CallableRegistry:
    """In-process registry mapping artifact ids to Python callables.

    Used to back ``skill`` and ``tool`` nodes until Skills v2 (E6) ships a
    durable skill registry; plugins and tests register callables explicitly.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._entries: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(
        self, ref_id: str, fn: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Register a callable for an artifact id.

        Args:
            ref_id: Artifact id in ``namespace/name`` format.
            fn: Callable receiving the rendered node input and returning the
                node output document.
        """
        self._entries[ref_id] = fn

    def get(self, ref_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Look up the callable registered for an artifact id.

        Args:
            ref_id: Artifact id in ``namespace/name`` format.

        Returns:
            The registered callable.

        Raises:
            UnsupportedNodeError: If nothing is registered under ``ref_id``.
        """
        if ref_id not in self._entries:
            raise UnsupportedNodeError(f"no callable registered for {ref_id!r}")
        return self._entries[ref_id]


def make_callable_handler(registry: CallableRegistry) -> NodeHandler:
    """Build a handler executing ``skill``/``tool`` nodes from a registry.

    Args:
        registry: Callable registry to resolve node refs against.

    Returns:
        A :class:`NodeHandler` for callable-backed nodes.
    """

    def handler(ctx: NodeContext) -> NodeOutcome:
        """Resolve the node ref and invoke the registered callable."""
        if ctx.node.ref is None:
            raise FlowNodeError(f"node {ctx.node.id!r} has no ref")
        fn = registry.get(ctx.node.ref.id)
        output = fn(dict(ctx.input))
        if not isinstance(output, dict):
            output = {"value": output}
        return NodeOutcome(output=output)

    return handler


def conditional_handler(ctx: NodeContext) -> NodeOutcome:
    """Handle ``conditional`` nodes: pure routing, no work.

    Args:
        ctx: Activation context.

    Returns:
        An empty outcome; routing happens on the node's guarded edges.
    """
    return NodeOutcome(output={})


def human_handler(ctx: NodeContext) -> NodeOutcome:
    """Handle ``human`` nodes: pause the run until a decision arrives (E3-S4).

    The ``waiting_human`` status tells the engine loop to persist the pause
    instead of completing the step. The output carries the request shown to
    operators: the node's ``prompt``, its decision ``form`` schema, and the
    computed ``expiresAt`` (ISO-8601, from ``timeoutSec`` and the engine's
    injectable wall clock) when the wait has an SLA.

    Args:
        ctx: Activation context.

    Returns:
        A pausing outcome with the pending-request document as output.
    """
    node = ctx.node
    expires_at: str | None = None
    if node.timeout_sec is not None:
        engine = ctx.services.get("engine")
        now_fn = getattr(engine, "now", None)
        current = now_fn() if callable(now_fn) else datetime.now(timezone.utc)
        expires_at = (current + timedelta(seconds=node.timeout_sec)).isoformat()
    return NodeOutcome(
        output={"prompt": node.prompt, "form": node.form, "expiresAt": expires_at},
        status="waiting_human",
    )


class AgentNodeHandler:
    """Executes ``agent`` nodes through the E2 Agent Registry and Runtime."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry | None = None,
        agent_runtime: AgentRuntime | None = None,
        store: Any | None = None,
        local_handlers: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            agent_registry: Registry used to resolve agent refs; defaults to a
                registry on the process-wide store.
            agent_runtime: Runtime used to execute agents; defaults to a stub
                -provider runtime.
            store: Durable store used to locate installed plugin directories.
            local_handlers: In-process agent handlers keyed by agent id,
                taking precedence over plugin-directory loading (used by
                tests and embedded deployments).
        """
        self._registry = agent_registry or AgentRegistry(store)
        self._runtime = agent_runtime or AgentRuntime()
        self._plugin_store = PluginStore(store) if store is not None else None
        self._local_handlers = dict(local_handlers or {})

    def register_local_handler(self, agent_id: str, handler: Any) -> None:
        """Register an in-process handler for an agent id.

        Args:
            agent_id: Fully qualified agent id.
            handler: Callable or ``run(ctx)`` object implementing the agent.
        """
        self._local_handlers[agent_id] = handler

    def __call__(self, ctx: NodeContext) -> NodeOutcome:
        """Resolve, load, and run the referenced agent.

        Args:
            ctx: Activation context.

        Returns:
            The agent's output and resource metrics.

        Raises:
            FlowNodeError: If the agent cannot be resolved/loaded, or the
                agent run does not complete.
        """
        if ctx.node.ref is None:
            raise FlowNodeError(f"node {ctx.node.id!r} has no ref")
        try:
            ref = self._registry.resolve(ctx.node.ref.id, ctx.node.ref.version_range)
        except KeyError as exc:
            raise FlowNodeError(str(exc)) from exc

        handler = self._local_handlers.get(ref.agent_id)
        if handler is None:
            handler = self._load_plugin_handler(ref.plugin_id, ref.manifest)

        result = self._runtime.run(
            ref.manifest,
            dict(ctx.input),
            handler,
            run_id=f"{ctx.run_id}:{ctx.node.id}",
            tenant_id=ctx.tenant_id,
        )
        if result.status != "completed" or result.output is None:
            raise FlowNodeError(
                f"agent {ref.agent_id!r} finished with status {result.status!r} "
                f"({result.stop_reason})"
            )
        tokens = float(result.metrics.get("tokens_input", 0)) + float(
            result.metrics.get("tokens_output", 0)
        )
        return NodeOutcome(
            output=result.output,
            metrics={
                "tokens": tokens,
                "cost_usd": float(result.metrics.get("cost_usd", 0.0)),
            },
        )

    def _load_plugin_handler(self, plugin_id: str, manifest: Any) -> Any:
        """Load an agent handler from its installed plugin directory.

        Args:
            plugin_id: Id of the plugin that registered the agent.
            manifest: The agent's manifest.

        Returns:
            The loaded handler.

        Raises:
            FlowNodeError: If the plugin's install location is unknown.
        """
        if self._plugin_store is None:
            raise FlowNodeError(
                f"no in-process handler for agent of plugin {plugin_id!r} and no "
                "plugin store configured"
            )
        row = self._plugin_store.get_plugin(plugin_id)
        if row is None or not row.get("manifest_path"):
            raise FlowNodeError(f"plugin {plugin_id!r} is not installed")
        base_dir = Path(str(row["manifest_path"])).parent
        return self._runtime.load_handler(manifest, base_dir)


class FlowHandlerRegistry:
    """Maps node types to their handlers."""

    def __init__(self) -> None:
        """Initialize an empty handler registry."""
        self._handlers: dict[str, NodeHandler] = {}

    def register(self, node_type: str, handler: NodeHandler) -> None:
        """Register (or replace) the handler for a node type.

        Args:
            node_type: Flow node type the handler executes.
            handler: The handler implementation.
        """
        self._handlers[node_type] = handler

    def get(self, node_type: str) -> NodeHandler:
        """Return the handler for a node type.

        Args:
            node_type: Flow node type to execute.

        Returns:
            The registered handler.

        Raises:
            UnsupportedNodeError: If the node type has no registered handler.
        """
        if node_type not in self._handlers:
            raise UnsupportedNodeError(
                f"node type {node_type!r} has no registered handler"
            )
        return self._handlers[node_type]


def build_default_handlers(
    *,
    store: Any | None = None,
    callables: CallableRegistry | None = None,
    agent_handler: AgentNodeHandler | None = None,
) -> FlowHandlerRegistry:
    """Build the default handler registry for the engine.

    All seven canonical node types are supported here: ``agent``, ``skill``,
    ``tool``, ``conditional``, ``human`` (E3-S4), and the composite
    ``subflow``/``map`` types (E3-S5). Unknown types fail closed via
    :class:`UnsupportedNodeError`.

    Args:
        store: Durable store shared with the engine.
        callables: Registry backing skill/tool nodes; created when omitted.
        agent_handler: Agent handler to use; created when omitted.

    Returns:
        The populated :class:`FlowHandlerRegistry`.
    """
    from backend.flows.composite import (  # deferred: avoid module cycle
        map_handler,
        subflow_handler,
    )

    registry = FlowHandlerRegistry()
    callable_registry = callables or CallableRegistry()
    callable_handler = make_callable_handler(callable_registry)
    registry.register("skill", callable_handler)
    registry.register("tool", callable_handler)
    registry.register("conditional", conditional_handler)
    registry.register("human", human_handler)
    registry.register("agent", agent_handler or AgentNodeHandler(store=store))
    registry.register("subflow", subflow_handler)
    registry.register("map", map_handler)
    return registry


__all__ = [
    "AgentNodeHandler",
    "CallableRegistry",
    "FlowBudgetExceededError",
    "FlowHandlerRegistry",
    "FlowNodeError",
    "NodeContext",
    "NodeHandler",
    "NodeOutcome",
    "UnsupportedNodeError",
    "build_default_handlers",
    "conditional_handler",
    "human_handler",
    "make_callable_handler",
]
