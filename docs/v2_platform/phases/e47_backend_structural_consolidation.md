# E47 — Backend Structural Consolidation

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E43: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/5
**Depends on:** E2/E2-S6 (registries + LLM gateway), E8 (adapters), E41/E43
(current orchestrator shape), E44 + E46 (land first — both modify
`orchestrator/service.py`, and S5 decomposes it after they stabilize)
**Enables:** the duplicated state machines and god-modules that make every
backend fix a two-place (or 2,000-line) change become single-definition:
one retry/fallback policy, one versioned-registry core, shared persistence
codecs, a cached agent catalog, and an orchestrator decomposed into
testable units.
**Canonical source:** two independent external code analyses
(2026-08-21), re-verified against the current tree (`943845f` + E43-S8
merge): `llm/gateway.py` `complete()` (~137 lines) and `_stream_prepared()`
(~185 lines) duplicate the full retry/fallback/budget/telemetry machine
with no backoff; `agents/registry_v2.py` (401 ln) and
`skills/registry_v2.py` (370 ln) share 15 structurally identical methods;
`agents_registry.py:116` rebuilds the agent map with dynamic imports +
instantiation on every `GET /agents`; `orchestrator/service.py` is 2,046
lines; both persistence adapters exceed the 500-line guideline (postgres
713 — its split is already a tracked follow-up in this tracker; sqlite
683).

## Objective

The efficiency epics (E44-E46) fix what the backend *does*; this epic
fixes what it *is*: consolidation that removes duplicated
correctness-critical logic and shrinks oversized modules, sequenced last
so structure is extracted from the final post-fix shape rather than
refactored twice. Risk profile is behavior-preserving refactor plus two
small behavior changes called out explicitly (catalog caching, retry
backoff).

## Key result

`GET /agents` does no imports/instantiation per request; retry/fallback
semantics are defined once and provably identical for streaming and
completion; a registry fix lands in one place; both adapters and the
orchestrator respect the 500-line-per-file guideline as decomposed
modules with focused tests.

## Stories

### E47-S1 — Agent catalog cache

Subtasks:
- `E47-S1-T1`: build the agent catalog once (startup or first use) —
  imports, instantiation, `metadata_model()` introspection move out of
  the request path (`backend/api/routers/agents_registry.py:116-186`).
- `E47-S1-T2`: invalidate/rebuild on extension enable/disable events
  (the E16-S4 delegated enable/disable path).
- `E47-S1-T3`: stop swallowing plugin/agent load failures to debug logs
  per request — failures surface once at build time with a clear log,
  and the entry is marked unavailable in the catalog.

| Criterion | Detail |
| --- | --- |
| Functional | Catalog contents identical; enable/disable reflected without process restart |
| Non-functional | Zero `importlib` calls during `GET /agents` after warm-up |
| DoR (specific) | none |
| DoD (specific) | Test asserting the builder runs once across N requests and rebuilds on invalidation |
| Dependencies | E16-S4 |

### E47-S2 — LLM gateway attempt coordinator

Subtasks:
- `E47-S2-T1`: extract the shared attempt machinery from `complete()`
  and `_stream_prepared()` — target iteration, capability-error
  recording, call/token budget checks, attempt numbering, retry/fallback
  decision (`RETRY | FALLBACK | FAIL`), telemetry recording — into one
  coordinator; the per-mode *execution* of an attempt stays separate
  (streaming's partial-emission semantics must not be forced into a
  single generator).
- `E47-S2-T2`: add basic backoff (small exponential + jitter, config
  default preserving current behavior when set to 0) between retries.
- `E47-S2-T3`: pin semantic parity with tests that run the same
  failure scripts through both paths and assert identical
  attempt/fallback/telemetry sequences.

| Criterion | Detail |
| --- | --- |
| Functional | Existing gateway behavior preserved (fallback order, budget enforcement, telemetry fields); E2-S6 contract tests stay green |
| Non-functional | Retry/fallback policy defined in exactly one module; both public paths ≤ ~60 lines of mode-specific code |
| DoR (specific) | none |
| DoD (specific) | Parity test matrix (capability error, retryable error, budget exhaustion, mid-stream failure) across both paths |
| Dependencies | E2-S6 (ADR-016 contracts) |

### E47-S3 — Unify Agent/Skill registries

Subtasks:
- `E47-S3-T1`: extract a shared versioned-extension-registry core (by
  composition, not a deep generic hierarchy) covering the 15 duplicated
  methods — register/resolve/deprecate/activate/catalog/schema/upsert/
  decode/version-matching.
- `E47-S3-T2`: `AgentRegistry` keeps `find_by_capability` +
  agent-manifest specifics; `SkillRegistry` keeps `find_by_trigger` +
  YAML loading; both delegate the rest.

| Criterion | Detail |
| --- | --- |
| Functional | Public registry APIs unchanged; existing registry + contract tests pass unmodified |
| Non-functional | Shared semantics implemented once (a version-resolution fix can no longer land in only one registry) |
| DoR (specific) | none |
| DoD (specific) | Both registries' existing test suites green with the shared core underneath |
| Dependencies | E2, E6 |

### E47-S4 — Shared persistence codecs and adapter split

Subtasks:
- `E47-S4-T1`: extract pure shared logic between SQLite/Postgres
  adapters — row→document codecs, timestamp normalization, batch
  preparation, step grouping (post-E44 shape) — into a shared module;
  SQL text, placeholders, RLS, and transaction details stay per-backend
  (explicitly **no** ORM and no `if postgres` generic adapter).
- `E47-S4-T2`: split both adapters into <500-line modules (e.g.
  store/plan-store per backend), closing the follow-up already recorded
  in this tracker for `postgres_adapter.py`.

| Criterion | Detail |
| --- | --- |
| Functional | Byte-identical persistence behavior; full persistence test suite green on both backends |
| Non-functional | No file over 500 lines in `backend/persistence/`; decode logic exists once |
| DoR (specific) | E44 landed (extract from the final query shapes, not the pre-fix ones) |
| DoD (specific) | Both backends' suites green; line-count guideline met |
| Dependencies | E44 |

### E47-S5 — OrchestratorService decomposition

Sequenced last: E44 (persistence call sites) and E46 (self-repair
gating) both edit `service.py`; decomposing first would force every one
of those changes through a refactor in flight.

Subtasks:
- `E47-S5-T1`: extract the execution-environment lifecycle
  (provision/bind/collect/teardown around `_process_tasks`) into a scope
  object.
- `E47-S5-T2`: introduce a typed per-task processing outcome so
  `_process_tasks` stops mutating results/steps/history lists in
  parallel at multiple points; extract task-outcome recording and the
  pending-decision path.
- `E47-S5-T3`: split `_build_execution_tasks`'s near-identical
  per-artifact loops into small explicit builders composed by
  chaining (no hidden dispatch).
- `E47-S5-T4`: move session/run summary building and the message-run
  job pathway into focused modules; `service.py` lands under the
  500-line guideline or is split into a package with each module under
  it.

| Criterion | Detail |
| --- | --- |
| Functional | Orchestrator behavior unchanged — existing unit/integration suites (begin_message, execution plan, self-repair, timeline events) pass unmodified |
| Non-functional | No module over 500 lines; environment lifecycle and task processing testable without a full service instance |
| DoR (specific) | E44-S1/S2/S3 and E46-S2 merged |
| DoD (specific) | Existing orchestrator test suites green; new focused tests for the extracted lifecycle scope |
| Dependencies | E44, E46 |

## Contracts & decisions

- No public `/v2` contract changes anywhere in this epic — it is
  internal consolidation; contract tests are the regression net.
- E47-S2 deliberately does **not** merge streaming and completion into
  one generator — shared *policy/bookkeeping*, separate *execution* —
  matching both analyses' warning against over-abstraction.
- E47-S4 deliberately rejects ORM/query-builder adoption; RLS and
  backend-specific SQL stay explicit.
- Explicit non-goals (both analyses agree these are healthy): FlowEngine
  `_run_loop`, `map_handler`'s budgeted scheduler loops,
  graph-validation DFS, and serialization comprehensions.

## DoR / DoD

- **DoR:** E44 and E46 merged (S4/S5 hard-depend; S1-S3 can start
  earlier if sequencing demands, since they touch disjoint files).
- **DoD:** all story DoDs met; every touched suite green; 500-line
  guideline satisfied for touched packages;
  `docs/v2_platform/progress.md` updated; no push/PR without explicit
  authorization.
