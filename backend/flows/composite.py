"""Composite node handlers: ``subflow`` and ``map`` (E3-S5).

Both handlers start child flow runs through the parent engine exposed as
``ctx.services["engine"]`` and link them to the parent via
``parent_run_id`` so the trace hierarchy is queryable
(:meth:`backend.flows.state.FlowRunStore.list_runs` with ``parent_run_id``).

Conventions (documented in ``docs/flows/engine.md`` and ADR-006):

- A ``subflow`` node's output is the child run's consolidated output spread at
  the top level plus the reserved key ``childRunId`` (which always wins on
  collision), keeping downstream bindings ergonomic
  (``nodes.<id>.output.<field>``).
- A ``map`` node renders its raw input bindings **per item** with the ``item``
  root bound to the current element (the engine's pre-rendered ``ctx.input``
  is ignored for map nodes). ``reduce: collect`` aggregates ordered child
  outputs into ``{"items": [...], "count": N, "childRunIds": [...]}``.
- Children run under a budget cap equal to the parent's remaining budget at
  spawn time; aggregate consumption is re-checked before each launch and after
  each completion, failing the parent step closed
  (:class:`backend.flows.handlers.FlowBudgetExceededError`).
- Composite nesting is bounded by :data:`MAX_COMPOSITE_DEPTH` (fail closed),
  which also stops recursive sub-flow definitions.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from backend.flows.expressions import ExpressionError, render_template
from backend.flows.handlers import (
    FlowBudgetExceededError,
    FlowNodeError,
    NodeContext,
    NodeOutcome,
)
from backend.flows.model import FlowBudgets, FlowManifest

MAX_COMPOSITE_DEPTH = 16
DEFAULT_MAP_PARALLELISM = 4


def _engine(ctx: NodeContext) -> Any:
    """Return the parent engine from the activation context services.

    Args:
        ctx: Activation context.

    Returns:
        The :class:`backend.flows.engine.FlowEngine` executing the parent run.

    Raises:
        FlowNodeError: If no engine service is available (fails closed).
    """
    engine = ctx.services.get("engine")
    if engine is None:
        raise FlowNodeError(
            f"node {ctx.node.id!r}: engine service unavailable for composite execution"
        )
    return engine


def _ensure_depth(engine: Any, ctx: NodeContext) -> None:
    """Fail closed when starting a child would exceed the composite depth cap.

    Walks the ``parent_run_id`` chain of the current run; recursive sub-flow
    definitions therefore terminate deterministically.

    Args:
        engine: The parent flow engine.
        ctx: Activation context.

    Raises:
        FlowNodeError: If the child run would exceed
            :data:`MAX_COMPOSITE_DEPTH`.
    """
    depth = 0
    current: str | None = ctx.run_id
    while current is not None and depth <= MAX_COMPOSITE_DEPTH:
        record = engine.runs.get_run(current)
        if record is None or record.parent_run_id is None:
            break
        depth += 1
        current = record.parent_run_id
    if depth + 1 > MAX_COMPOSITE_DEPTH:
        raise FlowNodeError(
            f"node {ctx.node.id!r}: max composite depth {MAX_COMPOSITE_DEPTH} "
            "exceeded; refusing to start another child flow "
            "(possible recursive sub-flow)"
        )


def _resolve_child_flow(engine: Any, ctx: NodeContext) -> FlowManifest:
    """Resolve the node's ref to a registered flow definition.

    Args:
        engine: The parent flow engine.
        ctx: Activation context.

    Returns:
        The resolved child :class:`FlowManifest`.

    Raises:
        FlowNodeError: If the node has no ref or the ref does not match a
            registered flow (composite refs reference flows in E3-S5).
    """
    ref = ctx.node.ref
    if ref is None:
        raise FlowNodeError(f"node {ctx.node.id!r} has no ref")
    try:
        return engine.registry.resolve(ref.id, ref.version_range)
    except KeyError as exc:
        raise FlowNodeError(
            f"node {ctx.node.id!r}: ref {ref.raw!r} does not match a registered flow"
        ) from exc


def _parent_budgets(ctx: NodeContext) -> FlowBudgets:
    """Return the parent run's effective budgets.

    Prefers the effective budgets the engine placed in ``ctx.services`` (which
    account for caps inherited from *its* parent); falls back to the manifest
    budgets.

    Args:
        ctx: Activation context.

    Returns:
        The parent's effective :class:`FlowBudgets`.
    """
    budgets = ctx.services.get("budgets")
    if isinstance(budgets, FlowBudgets):
        return budgets
    return ctx.manifest.budgets


def _wall_clock_remaining(ctx: NodeContext, budgets: FlowBudgets) -> int:
    """Compute the parent's remaining wall-clock budget, in whole seconds.

    Uses the deadline/clock services the engine provides; floors to an int so
    a child is never granted more time than the parent has left.

    Args:
        ctx: Activation context.
        budgets: The parent's effective budgets (fallback source).

    Returns:
        Remaining wall-clock seconds (>= 0).
    """
    deadline = ctx.services.get("deadline")
    clock = ctx.services.get("clock")
    if isinstance(deadline, (int, float)) and callable(clock):
        return max(0, int(deadline - clock()))
    return budgets.max_wall_clock_sec


def _child_cap(
    ctx: NodeContext,
    budgets: FlowBudgets,
    consumed_tokens: float,
    consumed_cost: float,
) -> FlowBudgets:
    """Build a child budget cap from the parent's remaining budget (ADR-006).

    Args:
        ctx: Activation context.
        budgets: The parent's effective budgets.
        consumed_tokens: Tokens already consumed against the parent budget
            (parent metrics plus finished sibling branches).
        consumed_cost: Cost (USD) already consumed against the parent budget.

    Returns:
        The cap to pass as ``budget_cap`` when starting the child run.
    """
    return FlowBudgets(
        max_cost_usd=max(0.0, budgets.max_cost_usd - consumed_cost),
        max_wall_clock_sec=_wall_clock_remaining(ctx, budgets),
        max_tokens=max(0, int(budgets.max_tokens - consumed_tokens)),
    )


def _child_metrics(record: Any) -> tuple[float, float]:
    """Extract a child run's accumulated (tokens, cost_usd) metrics.

    Args:
        record: The child's terminal :class:`FlowRunRecord`.

    Returns:
        A ``(tokens, cost_usd)`` tuple, zero when the child has no metrics.
    """
    state = record.state if isinstance(record.state, dict) else {}
    metrics = state.get("metrics", {}) if isinstance(state, dict) else {}
    return (
        float(metrics.get("tokens", 0.0)),
        float(metrics.get("cost_usd", 0.0)),
    )


def _base_eval_state(engine: Any, ctx: NodeContext) -> dict[str, Any]:
    """Build the state document map-node expressions render against.

    Args:
        engine: The parent flow engine.
        ctx: Activation context.

    Returns:
        A dict exposing ``flow.input`` and ``nodes.<id>.output``; map branches
        extend it with the ``item`` root.
    """
    record = engine.runs.get_run(ctx.run_id)
    run_input = record.input if record is not None else {}
    return {"flow": {"input": run_input}, "nodes": ctx.state.get("nodes", {})}


def _start_child(
    engine: Any,
    ctx: NodeContext,
    flow_id: str,
    version_range: str,
    child_input: dict[str, Any],
    trigger: dict[str, Any],
    cap: FlowBudgets,
) -> Any:
    """Start and synchronously execute a child run linked to the parent.

    Args:
        engine: The parent flow engine.
        ctx: Activation context of the composite node.
        flow_id: Resolved child flow id.
        version_range: SemVer range from the node ref.
        child_input: Rendered input payload for the child run.
        trigger: Trigger document recording the composite origin.
        cap: Budget cap from the parent's remaining budget.

    Returns:
        The child's terminal :class:`FlowRunRecord`.

    Raises:
        FlowNodeError: If the child run cannot be started (e.g. its input
            schema rejects the rendered payload).
    """
    from backend.flows.engine import FlowRunError  # deferred: avoid module cycle

    try:
        return engine.start_run(
            flow_id,
            version_range=version_range,
            input=child_input,
            trigger=trigger,
            tenant_id=ctx.tenant_id,
            parent_run_id=ctx.run_id,
            budget_cap=cap,
        )
    except FlowRunError as exc:
        raise FlowNodeError(
            f"node {ctx.node.id!r}: failed to start child flow {flow_id!r}: {exc}"
        ) from exc


def _raise_child_failure(ctx: NodeContext, child: Any, branch: int | None) -> None:
    """Raise the fail-closed error for a non-completed child run.

    Args:
        ctx: Activation context of the composite node.
        child: The child's terminal run record.
        branch: Map branch index, or ``None`` for sub-flow children.

    Raises:
        FlowBudgetExceededError: When the child stopped on
            ``budget_exhausted`` (propagates as the parent's stop reason).
        FlowNodeError: For any other child failure.
    """
    where = f"branch {branch} " if branch is not None else ""
    message = (
        f"node {ctx.node.id!r}: {where}child run {child.run_id} of flow "
        f"{child.flow_id!r} failed ({child.stop_reason or child.status})"
    )
    if child.stop_reason == "budget_exhausted":
        raise FlowBudgetExceededError(message)
    raise FlowNodeError(message)


def subflow_handler(ctx: NodeContext) -> NodeOutcome:
    """Execute a ``subflow`` node: run another flow as a child run.

    The child runs synchronously with ``parent_run_id`` linkage and a budget
    cap equal to the parent's remaining budget (ADR-006). Its accumulated
    metrics charge the parent's budget ledger.

    Args:
        ctx: Activation context; ``ctx.input`` is the child's run input.

    Returns:
        The child's consolidated output spread at the top level plus the
        reserved ``childRunId`` key; metrics carry the child's consumption.

    Raises:
        FlowBudgetExceededError: If the child stopped on ``budget_exhausted``.
        FlowNodeError: If the ref is unknown, the depth cap is exceeded, or
            the child run fails for any other reason (fails closed).
    """
    engine = _engine(ctx)
    _ensure_depth(engine, ctx)
    child_manifest = _resolve_child_flow(engine, ctx)
    ref = ctx.node.ref
    assert ref is not None  # noqa: S101 - guaranteed by _resolve_child_flow
    budgets = _parent_budgets(ctx)
    metrics = ctx.state.get("metrics", {})
    cap = _child_cap(
        ctx,
        budgets,
        float(metrics.get("tokens", 0.0)),
        float(metrics.get("cost_usd", 0.0)),
    )
    child = _start_child(
        engine,
        ctx,
        child_manifest.id,
        ref.version_range,
        dict(ctx.input),
        {"type": "subflow", "parentRunId": ctx.run_id, "nodeId": ctx.node.id},
        cap,
    )
    tokens, cost = _child_metrics(child)
    if child.status != "completed":
        _raise_child_failure(ctx, child, branch=None)
    output = dict(child.output or {})
    output["childRunId"] = child.run_id
    return NodeOutcome(output=output, metrics={"tokens": tokens, "cost_usd": cost})


def map_handler(ctx: NodeContext) -> NodeOutcome:
    """Execute a ``map`` node: fan a child flow out over a collection.

    Evaluates ``over`` against the run state (must yield a list), renders the
    node's raw input bindings per item with the ``item`` root bound to the
    current element, and executes one child run per item on a thread pool
    bounded by ``maxParallel`` (default :data:`DEFAULT_MAP_PARALLELISM`).
    Branches launch lazily: before each launch (and after each completion)
    the aggregate consumption is checked against the parent's remaining
    budget, so a breach stops launching, skips the remaining branches, and
    fails the step closed. ``reduce: collect`` preserves input order.

    Args:
        ctx: Activation context; ``ctx.node.input_bindings`` (raw) are
            re-rendered per item — the engine-rendered ``ctx.input`` is
            ignored for map nodes.

    Returns:
        ``{"items": [...], "count": N, "childRunIds": [...]}`` with outputs
        in input order; metrics aggregate every child's consumption.

    Raises:
        FlowBudgetExceededError: If aggregate child consumption breaches the
            parent's remaining budget, or a child stops on
            ``budget_exhausted``.
        FlowNodeError: If ``over`` does not yield a list, a binding fails to
            render, the ref is unknown, the depth cap is exceeded, or any
            child run fails (fails closed).
    """
    engine = _engine(ctx)
    _ensure_depth(engine, ctx)
    child_manifest = _resolve_child_flow(engine, ctx)
    node = ctx.node
    ref = node.ref
    assert ref is not None  # noqa: S101 - guaranteed by _resolve_child_flow
    if node.over is None:
        raise FlowNodeError(f"map node {node.id!r} has no 'over' expression")
    if node.reduce != "collect":
        raise FlowNodeError(
            f"map node {node.id!r}: unsupported reduce mode {node.reduce!r}"
        )
    base_state = _base_eval_state(engine, ctx)
    try:
        items = render_template(node.over, base_state)
    except ExpressionError as exc:
        raise FlowNodeError(
            f"map node {node.id!r}: 'over' failed to render: {exc}"
        ) from exc
    if not isinstance(items, list):
        raise FlowNodeError(
            f"map node {node.id!r}: 'over' must yield a list, "
            f"got {type(items).__name__}"
        )

    budgets = _parent_budgets(ctx)
    parent_metrics = ctx.state.get("metrics", {})
    base_tokens = float(parent_metrics.get("tokens", 0.0))
    base_cost = float(parent_metrics.get("cost_usd", 0.0))
    workers = node.max_parallel or DEFAULT_MAP_PARALLELISM
    outputs: list[dict[str, Any] | None] = [None] * len(items)
    child_run_ids: list[str | None] = [None] * len(items)
    children_tokens = 0.0
    children_cost = 0.0
    reserved_tokens = 0.0
    reserved_cost = 0.0
    granted: dict[int, tuple[float, float]] = {}

    def breach() -> str | None:
        """Describe an aggregate budget violation, or ``None`` when within."""
        if base_tokens + children_tokens > budgets.max_tokens:
            return (
                f"aggregate tokens {base_tokens + children_tokens} exceeded "
                f"budget {budgets.max_tokens}"
            )
        if base_cost + children_cost > budgets.max_cost_usd:
            return (
                f"aggregate cost {base_cost + children_cost} exceeded "
                f"budget {budgets.max_cost_usd} USD"
            )
        return None

    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending: dict[Future[Any], int] = {}
        while pending or next_index < len(items):
            while next_index < len(items) and len(pending) < workers:
                violation = breach()
                if violation is not None:
                    raise FlowBudgetExceededError(
                        f"map node {node.id!r}: {violation}"
                    )
                index = next_index
                next_index += 1
                try:
                    rendered = render_template(
                        dict(node.input_bindings),
                        {**base_state, "item": items[index]},
                    )
                except ExpressionError as exc:
                    raise FlowNodeError(
                        f"map node {node.id!r}: branch {index} bindings "
                        f"failed to render: {exc}"
                    ) from exc
                child_input = (
                    rendered if isinstance(rendered, dict) else {"value": rendered}
                )
                # In-flight reservation (ADR-006): each launching branch
                # gets an even share of the parent's *unreserved* remaining
                # budget, so concurrent branches can never jointly overspend
                # what only completed-child accounting would allow.
                remaining_tokens = max(
                    0.0,
                    budgets.max_tokens
                    - (base_tokens + children_tokens + reserved_tokens),
                )
                remaining_cost = max(
                    0.0,
                    budgets.max_cost_usd
                    - (base_cost + children_cost + reserved_cost),
                )
                divisor = float(max(1, min(workers, len(items) - index)))
                cap = FlowBudgets(
                    max_cost_usd=remaining_cost / divisor,
                    max_wall_clock_sec=_wall_clock_remaining(ctx, budgets),
                    max_tokens=int(remaining_tokens / divisor),
                )
                granted[index] = (float(cap.max_tokens), cap.max_cost_usd)
                reserved_tokens += float(cap.max_tokens)
                reserved_cost += cap.max_cost_usd
                future = pool.submit(
                    _start_child,
                    engine,
                    ctx,
                    child_manifest.id,
                    ref.version_range,
                    child_input,
                    {
                        "type": "map",
                        "parentRunId": ctx.run_id,
                        "nodeId": node.id,
                        "index": index,
                    },
                    cap,
                )
                pending[future] = index
            if not pending:
                break
            done, _ = wait(set(pending), return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                child = future.result()
                child_run_ids[index] = child.run_id
                tokens, cost = _child_metrics(child)
                grant_tokens, grant_cost = granted.pop(index)
                reserved_tokens -= grant_tokens
                reserved_cost -= grant_cost
                children_tokens += tokens
                children_cost += cost
                if child.status != "completed":
                    _raise_child_failure(ctx, child, branch=index)
                outputs[index] = dict(child.output or {})
            violation = breach()
            if violation is not None:
                raise FlowBudgetExceededError(f"map node {node.id!r}: {violation}")

    return NodeOutcome(
        output={
            "items": outputs,
            "count": len(items),
            "childRunIds": child_run_ids,
        },
        metrics={"tokens": children_tokens, "cost_usd": children_cost},
    )


__all__ = [
    "DEFAULT_MAP_PARALLELISM",
    "MAX_COMPOSITE_DEPTH",
    "map_handler",
    "subflow_handler",
]
