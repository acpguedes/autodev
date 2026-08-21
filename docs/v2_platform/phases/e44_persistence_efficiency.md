# E44 — Persistence Read/Write Efficiency

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E43: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/5
**Depends on:** E8 (persistence adapters + migrations), E16-S1 (turn
endpoints this epic makes O(1)), E43 (current run/step read paths)
**Enables:** Control Plane read/write cost that stays constant as
sessions, runs, messages, and steps accumulate — today every hot listing
endpoint degrades linearly (or quadratically, for step writes) with data
volume, which is incompatible with "controlled production".
**Canonical source:** two independent external code analyses
(2026-08-21), every claim re-verified against the current tree
(`943845f` + E43-S8 merge) before this epic was written — all confirmed,
none fixed since the analyzed commit.

## Objective

The State Store contracts were designed load-everything-first, and the
`/v2` listing endpoints paginate in memory on top of them. Verified
defects this epic removes:

1. **In-memory pagination.** `/v2/sessions` and the runs listing load
   *all* rows, then slice (`backend/api/routers/sessions_v2.py:305-306,
   363-366` via `backend/api/v2_common.py:64-77`); each session summary
   additionally issues a per-session `list_messages`
   (`backend/orchestrator/service.py:1515-1518`). Queries grow O(S).
2. **N+1 run steps.** Both adapters call `list_run_steps()` once per run
   inside `list_runs()` (`backend/persistence/postgres_adapter.py:230`,
   `backend/persistence/sqlite_adapter.py:210→487→496`), and each call
   opens a **fresh connection** — N+1 connections, not just queries.
3. **No direct run lookup.** `RunRepository`
   (`backend/persistence/base.py:41-74`) has no `get_run`;
   `GET /v2/turns/{turn_id}` therefore scans every session × every run
   (`backend/api/routers/chat_v2.py:150-172`, docstring admits it),
   compounding defects 1 and 2 — worst case ≈ `1 + 3S + R` queries to
   fetch one turn.
4. **Full-history reload on append.** `append_messages()` materializes
   the entire message history only to take `len(existing)`
   (`postgres_adapter.py:304-305`, `sqlite_adapter.py:261-262`) — total
   bytes read approach O(M²) over a conversation's life — and Postgres
   then inserts the new tail row-by-row (`:311-319`) while SQLite
   already uses `executemany`.
5. **Delete-and-reinsert step persistence.** Every `update_run` wipes
   all `run_steps` and re-inserts the full list
   (`sqlite_adapter.py:501-508`, `postgres_adapter.py:503-512`; Postgres
   per-row). With the step list growing every checkpoint, write volume
   is O(N²) per run, with the WAL/lock amplification that implies.

## Key result

`GET /v2/turns/{id}` costs ≤ 2 queries; session/run listings cost a
fixed 2-3 queries per page regardless of tenant size; appending a
message reads O(1) rows; persisting the Nth run step writes one row,
not N.

## Stories

### E44-S1 — Direct run/turn lookup

Add the missing primary-key read path and use it.

Subtasks:
- `E44-S1-T1`: add `get_run(run_id, tenant_id) -> dict | None` to the
  `RunRepository` protocol (`backend/persistence/base.py`) and both
  adapters (indexed `WHERE id = ? AND tenant_id = ?`; Postgres keeps RLS
  + explicit tenant filter; steps loaded in one second query).
- `E44-S1-T2`: expose `OrchestratorService.get_run(run_id, tenant_id)`
  returning the existing `RunSummary` shape (`KeyError` when absent).
- `E44-S1-T3`: rewrite `chat_v2._find_turn_by_id` to use it; delete the
  sessions × runs scan.
- `E44-S1-T4`: regression test asserting query count for
  `GET /v2/turns/{id}` (≤ 2 statements) on both adapters.

| Criterion | Detail |
| --- | --- |
| Functional | Turn lookup returns identical payloads to today for existing turns; unknown id still 404s; cross-tenant lookup returns nothing |
| Non-functional | ≤ 2 SQL statements per lookup, independent of session/run counts |
| DoR (specific) | none — contracts already identified |
| DoD (specific) | Statement-count test on both adapters; tenant-isolation negative test |
| Dependencies | E8-S1 (tenant scoping conventions) |

### E44-S2 — Batch step loading and batch inserts

Subtasks:
- `E44-S2-T1`: `list_runs()` becomes two queries in both adapters — runs
  for the session, then all steps `WHERE run_id IN (...)` ordered by
  run/sequence, grouped in memory; `_decode_run` becomes a pure function
  taking pre-fetched steps.
- `E44-S2-T2`: Postgres uses `executemany` for step and message inserts
  (parity with SQLite, which already does).
- `E44-S2-T3`: one connection per repository call, not per row/decoded
  run.

| Criterion | Detail |
| --- | --- |
| Functional | `list_runs` output byte-identical to today |
| Non-functional | 2 queries / 1 connection per `list_runs` call regardless of run count |
| DoR (specific) | none |
| DoD (specific) | Statement-count regression test with 1 and 100 runs |
| Dependencies | none |

### E44-S3 — Database-level pagination for listings

Subtasks:
- `E44-S3-T1`: add paged listing methods (limit/offset, SQL `LIMIT`/
  `OFFSET`, separate `COUNT(*)` only when the API needs a total) to the
  session/run repository protocols and both adapters. Note: no
  limit/offset exists anywhere in the adapters today for these paths —
  this is a protocol change, decided here rather than bolted on.
- `E44-S3-T2`: `/v2/sessions` and the runs listing consume the paged
  methods; `paginate()` in-memory slicing no longer used on these
  routes.
- `E44-S3-T3`: stop loading each session's message history to build
  list summaries — derive `message_count`/`last_activity` from a single
  aggregate query (or stored columns) instead of per-session
  `list_messages`.

| Criterion | Detail |
| --- | --- |
| Functional | Page contents/ordering and response schema unchanged for existing clients |
| Non-functional | 2-3 queries per listing request, independent of total sessions/runs |
| DoR (specific) | Agreement that listing summaries need not embed full history (they already only surface counts) |
| DoD (specific) | Statement-count test; pagination equivalence test vs. the in-memory result on a seeded store |
| Dependencies | E44-S2 (shared step batching), E16 (API response contracts) |

### E44-S4 — Incremental message append

Subtasks:
- `E44-S4-T1`: change the append contract so the persistence layer
  receives only the new tail (or derives it from
  `MAX(sequence)` computed inside the insert transaction), instead of
  the full history plus a re-read.
- `E44-S4-T2`: guard concurrency with a unique
  `(tenant_id, session_id, sequence)` constraint (migration via the
  existing `MigrationRunner`), so two concurrent appends cannot silently
  interleave.
- `E44-S4-T3`: update the orchestrator call sites to pass new messages
  explicitly.

| Criterion | Detail |
| --- | --- |
| Functional | Message ordering/sequence values identical to today under serial appends; concurrent appends fail closed instead of corrupting sequence |
| Non-functional | Rows read per append is O(1), not O(history) |
| DoR (specific) | Sequence-allocation semantics decided (MAX+1 in-transaction vs. passed-in start) |
| DoD (specific) | Unit test for the tail contract; concurrency test exercising the unique constraint |
| Dependencies | E8 (migrations) |

### E44-S5 — Incremental run-step persistence

Subtasks:
- `E44-S5-T1`: model steps as incremental records — append new steps
  and update changed ones (upsert keyed on `(run_id, step index/key)`)
  instead of `_replace_run_steps`'s DELETE + full re-insert.
- `E44-S5-T2`: migration adding the upsert key/constraint; keep a
  full-replace path only for import/recovery, clearly named.
- `E44-S5-T3`: verify `update_run` call sites (checkpointing during
  `_process_tasks`) only send changed/new steps.

| Criterion | Detail |
| --- | --- |
| Functional | Step contents after a full run identical to today; replays/recovery unaffected |
| Non-functional | Persisting the Nth step writes O(1) rows (total O(N) per run, down from O(N²)) |
| DoR (specific) | E44-S2 landed (decode path already takes pre-fetched steps) |
| DoD (specific) | Write-count regression test over a simulated multi-checkpoint run on both adapters |
| Dependencies | E44-S2, E8 (migrations) |

## Contracts & decisions

- Protocol changes (`get_run`, paged listings, tail-append, incremental
  steps) are additive where possible; where a signature must change
  (append), all callers are in-repo and updated in the same story.
- No ORM and no generic SQL abstraction layer — both adapters keep their
  explicit SQL (RLS and Postgres-specific behavior stay visible);
  shared *pure* codecs are E47-S4's scope, not this epic's.
- Explicit non-goals: caching layers, read replicas, and any change to
  event-store persistence (E8-S2 owns that surface).

## DoR / DoD

- **DoR:** evidence anchors above re-checked against HEAD when
  implementation starts (line numbers may drift; the defects were
  verified 2026-08-21).
- **DoD:** all story DoDs met; statement/connection counts asserted by
  tests, not just observed; `docs/v2_platform/progress.md` updated; no
  push/PR without explicit authorization.
