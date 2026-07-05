# ADR-006: Budget Propagation for Composite Nodes

- **Status:** Accepted
- **Date:** 2026-07-05
- **Authors:** AutoDev maintainers (via Claude Code)
- **Related epic:** E3 (story E3-S5)
- **Supersedes/Relates to:** ADR-004 (flow manifest and fail-closed budget
  defaults); RFC-002 (flow.yaml proposal).

## Context

E3-S5 introduces composite nodes: `subflow` runs another flow as a child run,
and `map` fans a child flow out over a collection. Child runs are real flow
runs with their own manifests — and their own declared budgets. Without a
propagation rule, a child could legally spend up to its *own* budget even when
the parent has almost nothing left, breaking the fail-closed guarantee that a
run never exceeds the budgets its manifest declares (reference doc Principle
2.5). The DoR for E3-S5 requires the propagation semantics to be defined
before implementation.

## Decision

1. **Parent-remaining capping.** When a composite node starts a child run, it
   passes a budget cap equal to the parent's *remaining* budget at spawn time.
   The child's effective budget is the element-wise minimum of its manifest
   budgets and that cap:
   - `maxTokens` / `maxCostUsd`: parent's effective limit minus the parent's
     accumulated consumption (run metrics plus, for `map`, the consumption of
     already-finished sibling branches). Floored at zero.
   - `maxWallClockSec`: the parent's remaining wall clock, computed from the
     parent execution's deadline and floored to whole seconds — a child is
     never granted more time than the parent has left.
   The cap persists in the child run's durable state (`state["budget_cap"]`)
   so resumed executions enforce the same limits. `FlowEngine.start_run` /
   `execute_run` accept an optional `budget_cap` (default `None`, backward
   compatible); the engine enforces `min(manifest budgets, cap)`.
2. **Effective budgets flow downward.** The engine exposes the *effective*
   budgets (not the manifest budgets) to handlers via the activation context
   services, so a capped parent caps its own children off the tighter number —
   nesting composes correctly at any depth.
3. **Aggregate fail-closed for map fan-out.** `map` launches branches lazily
   (bounded by `maxParallel`, default 4). Before every launch and after every
   completion it re-checks aggregate consumption (parent metrics + finished
   children) against the parent's remaining budget. On breach it stops
   launching, skips the remaining branches, and fails the step with
   `FlowBudgetExceededError`, which the engine maps to the
   `budget_exhausted` stop reason — the run fails, never silently truncates.
   In-flight branches (at most `maxParallel`) run to completion; unlaunched
   branches never start.
4. **Budget exhaustion propagates.** A child that stops on `budget_exhausted`
   fails its parent step with `FlowBudgetExceededError`, so the parent run
   also stops with `budget_exhausted` — the stop reason is preserved up the
   hierarchy instead of degrading to a generic node failure.
5. **Completion re-check.** The engine re-checks token/cost/wall-clock budgets
   once more before marking a run `completed`, so a terminal composite node
   whose children overspent can never yield a completed-but-over-budget run.
6. **Depth cap.** Composite nesting is bounded at 16
   (`backend.flows.composite.MAX_COMPOSITE_DEPTH`, handler-enforced by
   walking the `parent_run_id` chain). Exceeding it fails closed, which also
   terminates recursive sub-flow definitions deterministically.

## Alternatives considered

1. **Children keep their own manifest budgets (no cap)** — rejected: the
   parent's budget stops being an upper bound the moment it delegates work.
2. **Reserve budget slices per branch upfront (static partitioning)** —
   rejected: wastes budget on cheap branches and starves expensive ones;
   remaining-budget capping plus the aggregate re-check achieves the same
   ceiling without pre-partitioning.
3. **Hard-cancel in-flight branches on breach** — rejected for now: child runs
   execute synchronously in worker threads and cancellation would leave
   half-written run state; bounded in-flight overshoot (≤ `maxParallel`
   branches, each itself capped) is acceptable and the parent still fails
   closed. Revisit when the job queue (E5) executes branches out of process.

## Consequences

- **Positive:** the fail-closed budget guarantee now holds transitively across
  arbitrarily nested composition; hierarchical traces record which child
  consumed what (`childRunId(s)` in step outputs, `parent_run_id` linkage).
- **Negative / trade-offs:** concurrent branches capped from
  consumption-known-at-spawn can collectively overshoot the parent budget by
  at most the in-flight branches' spend; the aggregate re-check converts that
  into a parent failure rather than preventing it entirely.
- **Contract impact:** `FlowEngine.start_run`/`execute_run` gain an optional
  `budget_cap` parameter (additive); run state gains an optional
  `budget_cap` document; no migrations.

## Rollback plan

Revert the composite handlers and the `budget_cap` plumbing; `subflow`/`map`
nodes fall back to failing closed as `unsupported_node` (pre-E3-S5 behavior).
Persisted `budget_cap` state documents are ignored by older engines.

## References

- ADR-004; `docs/flows/spec.md`; `docs/flows/engine.md` (composite nodes
  section); `docs/architecture/v2_platform_reference.md` §3, Principle 2.5;
  `backend/flows/composite.py`, `backend/flows/budgets.py`.
