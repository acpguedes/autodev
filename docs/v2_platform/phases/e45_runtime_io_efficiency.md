# E45 — Runtime I/O Efficiency: Job Queue, Event Bus, SSE & Indexing

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E43: added after initial Beta
completion, before the wave is signed off).
**Status:** Done · **Stories:** 5/5
**Depends on:** E0 (Redis infrastructure), E8-S2 (event store), E9 (event
bus/SSE contracts), E43-S6 (chat turns now run on the job queue — the
highest-volume job type, making queue hygiene load-bearing)
**Enables:** an idle deployment that is actually idle (near-zero Redis
ops), SSE connections that release their resources on disconnect, bounded
memory/stream growth, and repository indexing that does not traverse
`.git`/`.venv`/`node_modules`.
**Canonical source:** two independent external code analyses
(2026-08-21), every claim re-verified against the current tree
(`943845f` + E43-S8 merge) — all confirmed (one nuance: the SSE loop is
event-driven with a 1 s timeout ceiling, not a fixed poll — under load it
issues *more* than one blocking XRANGE per second, not fewer).

## Objective

Verified defects this epic removes:

1. **Busy-polling worker.** `backend/jobs/queue.py:334-339` runs
   `while True: lpop; sleep(0.1)` — ~10 Redis ops/s per instance while
   idle; no `BLPOP`, no shutdown `threading.Event`, no `close()`, and the
   FastAPI lifespan (`backend/api/main.py:225-251`) starts the worker but
   never stops it.
2. **Job records never removed.** The in-memory backend's `stats()`
   scans every job ever enqueued on each metrics scrape
   (`queue.py:145-152` wired at `main.py:245-248`); Redis job hashes get
   no TTL (zero `expire` uses in `backend/`). Since E43-S6, every chat
   turn adds a permanent record.
3. **SSE subscriber leak.** The `EventBus` protocol has no unsubscribe
   (`backend/events/bus.py:45-64,67-93`) and the SSE generator has no
   `finally` cleanup (`backend/api/routers/runs_stream_v2.py:176-198`) —
   each connect permanently leaks a closure + `asyncio.Event` into the
   process-wide registry, iterated on every subsequent publish.
   Acknowledged in-code as a known limitation (`runs_stream_v2.py:36-37`).
4. **Blocking replay on the event loop.** `bus.replay_from()` executes a
   synchronous `XRANGE` on a sync Redis client from inside the async SSE
   generator (`runs_stream_v2.py:184`, `bus.py:230`); no async Redis
   exists anywhere in `backend/`.
5. **Unbounded streams/partitions.** `xadd` without `MAXLEN`
   (`bus.py:188-191`), no `XTRIM` anywhere; in-memory partitions grow
   forever and `replay_from`'s defaultdict access *creates* empty
   partitions for every run_id ever streamed (`bus.py:102,113,149`).
6. **Indexing over-traversal and row-at-a-time writes.**
   `sorted(root.rglob("*"))` materializes and sorts every path —
   including `.git`/`.venv`/`node_modules` — before filtering
   (`backend/repository/indexing.py:262-270`); one connection +
   transaction per file (`:182,205`) and one statement per chunk
   (`:197,216-236`); pgvector embedding *computation* is already batched
   but rows are inserted one by one
   (`backend/repository/embeddings/pgvector_store.py:125-138`).

## Key result

A quiescent deployment issues ~0 Redis operations; killing an SSE
connection frees its subscriber; Redis streams and job records have
bounded retention; reindexing a repository with a large `.venv` touches
only source files and persists in batches.

## Stories

### E45-S1 — Blocking job worker with graceful shutdown

Subtasks:
- `E45-S1-T1`: replace the LPOP/sleep loop with `BLPOP` (bounded
  timeout) for the Redis backend; the in-process backend keeps its
  current direct-dispatch behavior.
- `E45-S1-T2`: add a `threading.Event`-based stop signal and a
  `close()`/`stop()` method; keep a handle to the worker thread.
- `E45-S1-T3`: FastAPI lifespan shuts the worker down in its `finally`
  block (alongside `shutdown_observability()`).

| Criterion | Detail |
| --- | --- |
| Functional | Jobs still execute; enqueue-to-start latency does not regress (BLPOP wakes immediately) |
| Non-functional | Idle Redis ops from the worker ≈ 0 (one blocked BLPOP at a time); clean process exit without daemon-thread reliance |
| DoR (specific) | none |
| DoD (specific) | Test: worker stops within the BLPOP timeout after `close()`; no job loss across shutdown |
| Dependencies | E43-S6 (chat-turn jobs are the main consumer to not regress) |

### E45-S2 — Job-record retention and O(1) stats

Subtasks:
- `E45-S2-T1`: configurable TTL on Redis job hashes
  (`EXPIRE` on completion; setting with a sane default), so completed
  records age out.
- `E45-S2-T2`: in-memory backend removes/compacts completed records and
  keeps incremental pending/running counters so `stats()` stops scanning
  all jobs ever enqueued on every metrics scrape.

| Criterion | Detail |
| --- | --- |
| Functional | Job status remains queryable until the retention window elapses |
| Non-functional | `stats()` is O(1); memory/Redis usage bounded under sustained chat traffic |
| DoR (specific) | Retention default agreed (config-only knob, fail-safe) |
| DoD (specific) | Test asserting counter correctness across enqueue/run/fail/complete; TTL set on completed Redis hashes |
| Dependencies | E45-S1 |

### E45-S3 — Event-bus unsubscribe and SSE cleanup

Subtasks:
- `E45-S3-T1`: `subscribe()` returns a cancellation token/callable
  (additive protocol change); registry supports removal for both bus
  implementations.
- `E45-S3-T2`: the SSE generator unsubscribes in a `finally` block
  (covering client disconnect and `CancelledError`); remove the in-code
  "known limitation" note.

| Criterion | Detail |
| --- | --- |
| Functional | Events still delivered to live connections; replay behavior unchanged |
| Non-functional | Zero subscribers registered after N connect/disconnect cycles |
| DoR (specific) | none |
| DoD (specific) | Test: subscriber count returns to baseline after disconnect; publish after disconnect touches no dead callbacks |
| Dependencies | E9 (bus contract) |

### E45-S4 — Non-blocking replay and stream retention

Subtasks:
- `E45-S4-T1`: stop calling the synchronous `XRANGE` on the event loop —
  either offload `replay_from` to a thread (`asyncio.to_thread`/
  `run_in_threadpool`) or introduce `redis.asyncio` for the read path;
  decide by smallest safe diff (offload is the conservative default
  since no async Redis exists in the codebase yet).
- `E45-S4-T2`: publish with `XADD MAXLEN ~ N` (configurable) and/or
  time-based trimming so Redis streams stop growing unbounded; note the
  durable Event Store (E8-S2) remains the source of record — the bus
  stream is transport, so trimming it loses nothing durable.
- `E45-S4-T3`: bound in-memory partitions equivalently and fix the
  defaultdict read path so `replay_from` on an unknown run_id does not
  create an empty partition.

| Criterion | Detail |
| --- | --- |
| Functional | SSE replay + live tail behavior unchanged for retained windows; replay older than retention degrades explicitly (documented), backed by the durable Event Store |
| Non-functional | No synchronous Redis I/O on the event loop; stream length bounded |
| DoR (specific) | Retention default agreed and cross-checked with `autodev_event_retention_days` semantics (E8-S2) |
| DoD (specific) | Test with a blocked/slow replay proving the loop stays responsive; trim behavior asserted |
| Dependencies | E45-S3, E8-S2 |

### E45-S5 — Indexing traversal pruning and batched persistence

Subtasks:
- `E45-S5-T1`: replace `sorted(root.rglob("*"))` with an `os.walk`
  traversal that prunes `_IGNORED_DIRECTORIES` from `dirnames` in-place
  (never descends), streaming files instead of materializing/sorting the
  full path list.
- `E45-S5-T2`: batch persistence — one connection/transaction per batch
  of files (commit every ~100-500), `executemany` for chunk upserts and
  deletes instead of one statement per chunk.
- `E45-S5-T3`: batch pgvector row writes (`executemany`) in
  `upsert_embeddings` — noting it currently has no non-test caller, so
  this is hygiene for when E7's pipeline wires it, not a hot-path fix.

| Criterion | Detail |
| --- | --- |
| Functional | Index contents identical for the same tree (same chunks, same hashes) |
| Non-functional | A tree with a large `.venv`/`node_modules` indexes without entering those directories; SQL statements per reindex drop from O(chunks) executes to O(batches) |
| DoR (specific) | none |
| DoD (specific) | Test with an ignored-dir fixture asserting it is never visited (e.g. permission-trapped dir); statement-count assertion |
| Dependencies | E7 (index consumers unchanged) |

## Contracts & decisions

- `subscribe()` returning a cancellation token is an additive change to
  the `EventBus` protocol; existing publishers are untouched.
- The Redis event stream is treated as *transport with retention*, not
  the durable record — the E8-S2 Event Store keeps full history. This is
  the decision that makes `MAXLEN` trimming safe.
- Explicit non-goals: the SSE long-connection loop itself (legitimate),
  the `map_handler` scheduler and FlowEngine `_run_loop` (both analyses
  agree these loops are semantic, not waste), and any new queue
  technology — this epic tunes what exists.

## DoR / DoD

- **DoR:** evidence anchors re-checked against HEAD at implementation
  start.
- **DoD:** all story DoDs met; idle-ops / leak / retention assertions
  exist as tests; `docs/v2_platform/progress.md` updated; no push/PR
  without explicit authorization.
