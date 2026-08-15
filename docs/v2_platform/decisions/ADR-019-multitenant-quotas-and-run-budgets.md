# ADR-019: Multi-Tenant Isolation, Quotas, and Run Budgets

- **Status:** Accepted
- **Date:** 2026-08-15
- **Authors:** AutoDev maintainers
- **Related epic:** E11-S3
- **Supersedes/Relates to:** Extends ADR-010 (E8-S1 multi-tenancy primitives)
  and ADR-018 (E11-S2 authenticated `PrincipalV2`).

## Context

E8-S1 added the primitives to scope a query to a tenant
(`backend/persistence/tenancy.py`: `set_postgres_tenant`,
`sqlite_tenant_clause`) but did not retrofit every repository method's call
sites, and nothing selected the tenant authoritatively — most routes still
took (or ignored) a request-supplied value. E11-S2 fixed authentication and
authorization but left tenant *isolation* and *resource accounting* open:
today a tenant can, in places, read or mutate another tenant's runs, plans,
events, and artifacts, and no run or tenant has a resource ceiling that
actually stops execution. E11-S3 must close both gaps without inventing
billing, invoices, retention/purge policies, or general FinOps/IAM tooling.

## Decision

- **Tenant context is principal-authoritative.** The authenticated E11-S2
  `PrincipalV2.tenant_id` is the only source of truth for which tenant a
  request acts within. A request body, query parameter, or header may never
  select a tenant; any transitional tenant-shaped value a client does send
  must equal `principal.tenant_id` or the request receives the resource's
  ordinary not-found response (never a distinguishing error that would leak
  the resource's existence to another tenant).

- **Scoping strategy.** Tenant-owned roots and independently addressable
  rows carry a direct `tenant_id` column/predicate. Child rows stay
  transitively scoped through their parent — no denormalized `tenant_id`
  copy — only when *every* repository method that reads or writes them joins
  the protected parent, and PostgreSQL Row-Level Security proves the
  relationship with an `EXISTS` subquery against the parent. Any child that
  is independently addressable (has its own `GET /resource/{id}`) or lacks a
  mandatory protected-parent path gets its own direct `tenant_id` instead.

- **PostgreSQL enforces this with forced RLS.** Every tenant-scoped table
  gets `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` (so even
  the table owner is bound by policy), reading the active tenant from
  `current_setting('app.tenant_id', true)`. The application sets that GUC
  transaction-locally via `set_config('app.tenant_id', tenant_id, true)`
  (`backend/persistence/tenancy.py:set_postgres_tenant`) at the start of
  every request's transaction. A missing setting never falls back to
  unscoped access — policies treat an empty/unset GUC as matching nothing.

- **SQLite enforces this with explicit predicates.** SQLite has no RLS
  equivalent; every repository method appends the shared tenant predicate
  (`sqlite_tenant_clause`) or an explicit parent join, and this is proven by
  cross-tenant isolation tests rather than a database-level guarantee.

- **Quotas and budgets are database-authoritative; Redis is a disposable
  cache only.** PostgreSQL/SQLite own tenant policy, concurrency leases,
  storage reservations, monthly usage windows, and run-budget ledgers.
  Redis, when configured, may cache a policy snapshot or a usage read for
  latency — it never makes an admission decision on its own, and its absence
  or eviction never changes correctness, only cache-miss latency.

- **UTC calendar-month windows; fixed one-second request windows.** Monthly
  token/cost usage resets at UTC midnight on the 1st of each month
  (`utc_month_window`). Per-credential request-rate limiting uses a fixed
  one-second window (not a sliding/token-bucket approximation) — simple,
  auditable, and sufficient at this scale.

- **90-second run leases, 30-second heartbeats.** A run holds a concurrency
  lease for 90 seconds, renewed by a 30-second heartbeat while active. A
  lease that outlives 90 seconds without a heartbeat is reclaimable by any
  worker, so a crashed process cannot permanently pin a tenant's concurrency
  slot.

- **Admission reserves before external work; settlement records the
  actual.** Storage writes, model-provider attempts, and run budgets all
  follow reserve-then-settle: an estimate is reserved atomically before the
  external call, and the actual usage is settled (success, failure, or
  retry all settle independently) afterward. This bounds worst-case
  overspend to the reservation size, not to whatever an unbounded call
  might consume, and it means failed/retried attempts are still billed —
  metering only what providers actually did, not just what succeeded.

- **Money is always integer micro-USD.** 1 USD = 1,000,000 micro-USD
  (`usd_to_micros`). No dollar amount is ever stored or compared as a
  float; the existing `FlowBudgets.max_cost_usd: float` stays as a
  human-facing convenience field, converted to micro-USD at the boundary
  where E11-S3 budgets take over.

- **Local-mode finite defaults** (no explicit tenant policy configured):
  4 concurrent runs, 1 GiB stored artifacts, 20 requests/second, 20,000,000
  tokens and 100,000,000 micro-USD per UTC month. The default per-run
  budget preserves the existing ceilings already in `FlowBudgets`:
  2,000,000 tokens, 10,000,000 micro-USD (= the existing `max_cost_usd:
  10.0`), 3,600,000 ms (= the existing `max_wall_clock_sec: 3600`), and
  1,000 steps.

- **Production fails closed.** A production deployment with no explicit,
  durably-stored quota policy for a tenant, an unmetered provider result, or
  an unpriced model, denies rather than silently falling back to the local
  defaults or an unbounded run. Local mode is the only place the finite
  defaults above apply automatically.

- **Warnings and events are deduplicated.** Crossing the configured warning
  ratio (default 8,000 basis points = 80%) emits exactly one durable warning
  per resource/window, not one per request. Budget exhaustion emits exactly
  one canonical `run.budget_exhausted` event per run, from the same
  compare-and-set operation that first observes the exhaustion — concurrent
  callers racing the same limit cannot double-fire it.

- **No tenant/subject/run identity in Prometheus labels.** Metrics aggregate
  only by low-cardinality dimension and outcome (resource, reason, status).
  Tenant-, subject-, credential-, run-, and session-scoped detail is only
  ever available through authorized APIs and durable events/traces — the
  same policy E11-S1 already applies to observability metrics.

- **Explicitly out of scope.** Billing, invoices, plan catalogs, retention
  or purge jobs, and general FinOps/IAM functionality. E11-S3 enforces
  limits an operator has already configured; it does not decide what those
  limits should be commercially or bill for usage.

## Consequences

- Every route that reads or writes tenant-owned data must resolve its
  tenant exclusively from `principal.tenant_id`, and every new tenant-scoped
  table needs both a PostgreSQL RLS policy and a SQLite predicate/parent-join
  equivalent, proven by paired isolation tests.
- The orchestrator, flow engine, agent runtime, and model gateway all thread
  one shared `RunBudgetHandle` rather than each independently tracking (and
  potentially resetting) budget state.
- Operators configure tenant policy explicitly in production; there is no
  implicit "just works" fallback there, matching the fail-closed posture
  E11-S1 and E11-S4 already established for observability and execution
  security.
