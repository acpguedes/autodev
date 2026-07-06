# ADR-011: pgvector HNSW Index for Code Chunk Embeddings

- **Status:** Accepted
- **Date:** 2026-07-06
- **Authors:** AutoDev Team
- **Related epic:** E7 (Context & RAG), E7-S2 — Embeddings and Vector Store (pgvector)
- **Supersedes/Relates to:** ADR-010 (Scoped E8-S1 Tenancy Slice for E7)

## Context

E7-S2 requires an ANN (approximate-nearest-neighbor) index over
`code_embeddings.embedding` so hybrid retrieval (E7-S3) can find the top-k
most similar chunks to a query embedding without a full table scan. pgvector
offers two index types for this: **IVFFlat** (inverted file with flat
compression — clusters vectors into lists, searches only the nearest
lists) and **HNSW** (hierarchical navigable small world graph). The
reference architecture's non-functional target for this story is ANN query
p95 < 150 ms at 1M vectors (`docs/v2_platform/phases/e7_context_rag.md`,
E7-S2 CNF); the DoR explicitly requires "index choice (HNSW vs. IVFFlat)
recorded in an ADR" before this story is done.

## Decision

Use **HNSW** (`USING hnsw (embedding vector_cosine_ops)`) for the
`code_embeddings` ANN index, with cosine distance as the operator class
(matching `StubEmbeddingProvider`'s L2-normalized output and the `<=>`
operator used in `query_top_k()`).

Rationale:

- **Read-latency-sensitive workload.** Context retrieval sits on an agent's
  request path (E7's key result targets p95 <= 300 ms end-to-end for hybrid
  retrieval); HNSW's graph search gives substantially better recall at a
  given latency (or lower latency at a given recall) than IVFFlat, which is
  the standard trade-off documented by pgvector itself and the broader ANN
  literature.
- **No `lists` tuning burden.** IVFFlat's recall/latency is sensitive to the
  `lists` parameter (rule-of-thumb `rows / 1000` for a well-populated table)
  and degrades on tables that grow well past what `lists` was tuned for —
  exactly the shape of a live, continuously-reindexed code corpus. HNSW has
  no equivalent global tuning parameter that decays as the corpus grows.
- **Build cost is acceptable here.** HNSW build/insert is slower and more
  memory-hungry than IVFFlat, but E7-S1's incremental, hash-deduplicated
  reindexing (only changed chunks are re-embedded/upserted — see
  `backend/repository/indexing.py` and
  `backend/repository/embeddings/pgvector_store.py::upsert_embeddings`) keeps
  the steady-state write volume small; this is a read-heavy, write-light
  workload, which is exactly HNSW's strong side of the trade-off.

## Alternatives considered

1. **IVFFlat.** Rejected as the primary index — cheaper to build and lower
   memory, but recall degrades as the corpus grows past the tuned `lists`
   value without a re-`CREATE INDEX`, and query latency at comparable recall
   is generally worse than HNSW. Could be revisited for a memory-constrained
   deployment profile in the future (a future ADR, not this one).
2. **No ANN index (sequential scan / exact search).** Rejected — acceptable
   only at small scale; does not meet the p95 < 150 ms @ 1M vectors target
   and does not scale with the corpus.
3. **A dedicated vector database (e.g. Qdrant, Pinecone, Weaviate).** Rejected
   per this repository's stated OSS-first stack preference ("pgvector before
   introducing a dedicated vector database", root `CLAUDE.md`) — pgvector
   keeps the vector store colocated with the rest of the durable state (one
   fewer service to operate, one fewer place cross-tenant isolation must be
   independently enforced) and is sufficient at the scale this epic targets.

## Consequences

- **Positive:** Query-time recall/latency profile matches the retrieval
  NFR without per-deployment index tuning; the vector store stays inside
  PostgreSQL, reusing the same tenancy/RLS model as every other table
  (ADR-010) and the same connection/migration machinery.
- **Negative / trade-offs:** HNSW index build and incremental insert are
  more CPU/memory-intensive than IVFFlat; this is judged acceptable given
  the hash-deduplicated write path keeps steady-state writes small. No
  formal recall/latency benchmark suite is included in this story (explicitly
  descoped — see the epic's scope notes); the reasoning above is a design
  justification, not a measured benchmark result.
- **Contract impact:** Additive migration only (`_pg_m4_create_code_embeddings_table`
  in `backend/persistence/migrations/postgres_versions.py`); reversible via
  its paired down migration (drops the table; the `vector` extension itself
  is left installed since it is cluster/database-wide).

## Rollback plan

`_pg_m4_down_drop_code_embeddings_table` drops the `code_embeddings` table
(and with it, the HNSW index and RLS policy). Switching to IVFFlat later
would be a new migration (`DROP INDEX` + `CREATE INDEX ... USING ivfflat`),
not a schema change to the table itself.

## References

- ADR-010 (Scoped E8-S1 Tenancy Slice for E7) — the tenant_id/RLS pattern
  `code_embeddings` follows.
- `docs/v2_platform/phases/e7_context_rag.md` (E7-S2 CF/CNF/DoR/DoD)
- `backend/persistence/migrations/postgres_versions.py::_pg_m4_create_code_embeddings_table`
- `backend/repository/embeddings/pgvector_store.py`
- pgvector documentation on `ivfflat` vs `hnsw` index types.
