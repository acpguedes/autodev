# E7 — Context & RAG

**Wave:** Beta
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E1, E2, E8, E5 (for retrieval eval)
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
      story-specific DoD above.
- [ ] Contract tests green for the Context Provider, Retriever, and EmbeddingProvider
      extension points.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "Context & RAG (pgvector, hybrid retrieval)" satisfied (§18.9).
