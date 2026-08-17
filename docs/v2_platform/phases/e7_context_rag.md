# E7 — Context & RAG

**Wave:** Beta
**Status:** Done · **Stories:** 4/4 complete
**Depends on:** E1, E2, E8, E5 (for retrieval eval) — E8's full multi-tenant
story had not started when this epic began; a scoped E8-S1 tenancy slice
(tenant_id + RLS, reversible migrations) was implemented as an E7-S0
prerequisite instead of blocking on E8 — see
`decisions/ADR-010-e8s1-scoped-tenancy.md`. E5's retrieval-eval integration
is not wired up in this epic (E5 gates a future retrieval-quality
evaluation, not core retrieval itself).
**Enables:** context for agents/flows platform-wide
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.1 (E7), §18.8, §18.9

## Objective

Provide the **Context/RAG Service** with tree-sitter indexing, embeddings in a
**Vector Store (pgvector)**, hybrid retrieval (lexical + vector), and pluggable
**Context Providers**, serving code context to agents and flows.

## Key result

An agent/flow obtains, via a stable contract, the N most relevant snippets of an
indexed repository in <= 300 ms (p95) for warm queries, with source attribution and
no cross-tenant leakage.

## Stories

### E7-S1 — tree-sitter indexing pipeline

Subtasks:
- `E7-S1-T1`: incremental multi-language parser via tree-sitter; symbol extraction (functions, classes, imports).
- `E7-S1-T2`: syntax-aware chunking (symbol boundaries, configurable overlap).
- `E7-S1-T3`: incremental indexing queue on Redis, triggered by `repo.file.changed` events.
- `E7-S1-T4`: chunk metadata persistence (file, span, symbol, hash) in the State Store.

| Item | Content |
| --- | --- |
| CF (functional) | Indexes >= 10 languages; reindexes only changed files (delta); exposes `index(repo)`/`reindex(paths)`; records provenance for every chunk |
| CNF (non-functional) | Indexing a 100k-LOC repo < 5 min on the reference node; idempotent; a parse failure does not abort the batch |
| DoR | E0 (config/observability) and E8 (base schema) ready; target languages prioritized; tree-sitter grammars pinned by version |
| DoD | CF/CNF green; Context Provider contract test; indexing traces emitted; language-support docs published |
| Dependencies | E0, E8 |

### E7-S2 — Embeddings and Vector Store (pgvector)

Subtasks:
- `E7-S2-T1`: pluggable `EmbeddingProvider` abstraction (local stub, external provider).
- `E7-S2-T2`: pgvector schema with an HNSW/IVFFlat index and a `tenant_id` column.
- `E7-S2-T3`: batch/upsert embeddings with dedup by chunk hash.
- `E7-S2-T4`: deterministic stub fallback for local-first mode (no external provider).

| Item | Content |
| --- | --- |
| CF | Generates and persists embeddings per chunk; ANN top-k query; switching provider does not force reindexing when the dimension is compatible |
| CNF | ANN query p95 < 150 ms for 1M vectors; per-tenant isolation guaranteed in the filter; configurable dimension |
| DoR | E7-S1 done; index choice (HNSW vs. IVFFlat) recorded in an ADR |
| DoD | Recall/latency benchmark attached; EmbeddingProvider contract test; reversible pgvector migration |
| Dependencies | E7-S1, E8 |

### E7-S3 — Hybrid retrieval (lexical + vector)

Subtasks:
- `E7-S3-T1`: lexical retriever (PostgreSQL BM25/full-text).
- `E7-S3-T2`: rank fusion (Reciprocal Rank Fusion) between lexical and vector.
- `E7-S3-T3`: optional pluggable reranking and path/symbol/language filters.
- `E7-S3-T4`: context token budget with relevance-based truncation.

| Item | Content |
| --- | --- |
| CF | `retrieve(query, filters, budget)` returns snippets with score and source; supports lexical, vector, and hybrid modes |
| CNF | p95 < 300 ms on a warm query; recall@10 >= the documented baseline on the retrieval evaluation set |
| DoR | E7-S2 ready; retrieval evaluation dataset defined |
| DoD | Recall/latency metrics in the Evaluation Service; Retriever contract test; fusion configuration docs |
| Dependencies | E7-S1, E7-S2, E5 (for retrieval eval) |

### E7-S4 — Pluggable Context Providers

Subtasks:
- `E7-S4-T1`: `ContextProvider` extension point (files, symbols, session memory).
- `E7-S4-T2`: composition/prioritization of multiple providers with dedup.
- `E7-S4-T3`: Agent Runtime integration (policy-driven context injection).
- `E7-S4-T4`: persisted session-memory provider.

| Item | Content |
| --- | --- |
| CF | Providers register via the Plugin Host; the agent receives composed, attributable context; order/weight configurable per flow |
| CNF | Provider isolated (explicit permissions); per-provider timeout; one provider failing does not bring down the run |
| DoR | E1 (Plugin Host) and E2 (Agent Runtime) ready; ContextProvider contract approved |
| DoD | Example provider published; contract test; per-step context traces |
| Dependencies | E1, E2, E7-S3 |

## v1 precursor / starting point

- `backend/repository/intelligence.py` already exposes a file inventory and ranked
  candidate-file retrieval (`GET /repository/context`), and a pluggable provider
  system exists (`backend/repository/providers/{lexical,treesitter}_provider.py`,
  `GET /repository/symbols`) — the tree-sitter provider currently falls back to
  lexical extraction whenever the `tree_sitter` package is absent, and there is no
  embedding step, no pgvector, and no hybrid ranking. This is the direct precursor to
  E7-S1, but E7-S2/E7-S3/E7-S4 (embeddings, pgvector, RRF fusion, Context Provider
  extension point) start from zero.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above. **Partially met.** Two passes closed the
      deferred items: **2026-08-10** on this branch (PR #99) and **2026-08-17**
      on `epic/gap-closure-alpha` (PR #100), which duplicated part of the same
      work before this branch merged. Where the two overlapped -- indexing and
      context tracing -- the version already merged to `main` was kept; where
      they were complementary, both landed. The reconciliation is recorded in
      the merge commit on this branch.

  **Closed:**
  - E7-S1 "indexing traces emitted" — `autodev.repository.index` / `.reindex`
    spans with file/chunk counts (`trace_indexing` in
    `backend/observability/tracing.py`). Counts only; repository and file paths
    never reach a span.
  - E7-S4 "per-step context traces" — `autodev.context.compose` parenting one
    `autodev.context.provider` span per provider. PR #99 argued child spans
    could not be emitted honestly, because a span opened around
    `future.result()` times this thread's wait rather than the provider, and a
    timed-out provider could never be closed. That objection is correct for
    that design and is answered by a different one: the span is started **on
    the worker thread** with the composition's OpenTelemetry context attached,
    so it measures the provider's real execution and closes honestly even after
    the composer has stopped waiting. Failures carry the exception *type*, never
    its message (provider errors routinely embed DSNs with credentials).
    Evidence: `backend/tests/unit/observability/test_context_indexing_tracing.py`.
  - E7-S3 "fusion configuration" — `retrieve()` and `GET /v2/context/retrieve`
    now accept `fusion_k` / `lexical_weight` / `vector_weight` and echo the
    effective configuration (PR #99). Before this, `reciprocal_rank_fusion`
    accepted `k`/`weights` but no caller forwarded them, so there was no
    configuration surface to document at all. Documented in
    [`docs/context/retrieval.md`](../../context/retrieval.md), with
    `test_retrieval_fusion_config.py` covering it.
  - E7-S1 "language-support docs published" — `docs/context/retrieval.md`
    § Language support, including the procedure for registering a grammar and
    the `RetrievalFilters.language` no-op limit. **Scope note:** this closes the
    *documentation* item only. The story's CF ("Indexes >= 10 languages") is
    unmet **in code** — `_LANGUAGE_REGISTRY` and `_INDEXED_EXTENSIONS` cover
    Python alone — so the checklist box above stays unticked. Adding languages
    is its own story, not a documentation gap.
  - E7-S2 "Recall/latency benchmark attached" — **harness only.**
    `backend/repository/retrieval/benchmark.py` (recall@k, MRR, nearest-rank
    p50/p95) plus the `scripts/benchmark_retrieval.py` CLI with
    `--max-p95-ms` / `--min-recall` gating. The metric definitions are
    unit-tested offline; **no numbers have been measured** — that needs a live
    PostgreSQL + pgvector instance and a curated label set, and every E7 test
    monkeypatches the database, so no honest measurement exists yet.

  **Still open:**
  - E7-S1 CF "Indexes >= 10 languages" — a code gap, see the scope note above.
  - E7-S3 "Recall/latency metrics in the Evaluation Service" — the benchmark is
    a standalone CLI and `backend/evals/` carries nothing retrieval-shaped.
    Closing it needs an `EvalSpec` plus a retrieval-metrics evaluator kind so
    retrieval quality reaches `ScoreSnapshot`s alongside agent evals. That is a
    new surface, not wiring.

  **Adjacent finding (not an E7 DoD item), 2026-08-17.** The tracing work
  surfaced a real contract violation in `ContextComposer.compose`: its
  docstring promises a timed-out provider "never blocks the other providers'
  results", but the surrounding `with ThreadPoolExecutor(...)` calls
  `shutdown(wait=True)` on exit, so `compose()` itself does not return until
  every worker finishes — a provider hanging for 30 s stalls the caller for
  30 s despite a 5 s timeout. Pinned (not fixed) by
  `test_timed_out_provider_span_records_its_real_duration`. Fixing it means
  managing the executor manually with `shutdown(wait=False,
  cancel_futures=True)` and owning the thread-leak trade-off; it belongs in an
  E7 follow-up or E26.
- [x] Contract tests green for the Context Provider, Retriever, and EmbeddingProvider
      extension points (`test_context_providers.py`, `test_retrieval_retriever.py`,
      `test_context_api.py`, `test_embeddings_pgvector.py`).
- [x] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "Context & RAG (pgvector, hybrid retrieval)" satisfied (§18.9)
      — functionally implemented, but the wave-gate CNF ("Hybrid retrieval reaches
      p95 < 300 ms and the recall baseline") is unverified without a live
      PostgreSQL/pgvector benchmark, which this pass did not run.
