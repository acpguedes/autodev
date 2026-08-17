# Context indexing and hybrid retrieval

Public configuration reference for the E7 Context & RAG subsystem: which
languages are indexed, how the hybrid retriever fuses lexical and vector
results, what is observable, and how to reproduce the recall/latency numbers
the v2.0-beta wave gate asks for.

This page closes the E7-S1 "language-support docs" and E7-S3
"fusion-configuration doc" DoD items. It states the current limits explicitly
rather than describing the design intent, so a reader can tell what is wired
today from what the contract leaves room for.

## Language support

Chunking is symbol-aware where a tree-sitter grammar is registered, and falls
back to a lexical splitter otherwise.

| Language | Parser | Status |
| --- | --- | --- |
| Python | tree-sitter (`tree-sitter-python`, vendored in `backend/requirements.txt`) | Symbol-aware chunks (functions, classes) |
| Everything else | `LexicalProvider` | Fallback: whole-file / line-window chunks, no symbol attribution |

`index()` only walks files whose extension is in `_INDEXED_EXTENSIONS`
(`backend/repository/indexing.py`), which is `.py` today. A file of any other
type is never indexed, so the lexical fallback is reached through explicit
`chunk_source(..., language=...)` calls, not through a repository walk.

### Adding a language

1. Add the grammar package to `backend/requirements.txt`.
2. Add a loader entry to `_LANGUAGE_REGISTRY` in
   `backend/repository/providers/treesitter_provider.py` — a callable
   returning a `tree_sitter.Language`, keyed by the language name.
3. Add the file extension to `_INDEXED_EXTENSIONS` in
   `backend/repository/indexing.py` so the walker picks it up.
4. Extend `chunk_source`'s node-type vocabulary if the new grammar names its
   definition nodes differently.

The extractor degrades rather than fails: a missing `tree_sitter` install, an
unregistered language, or a parse error all fall back to `LexicalProvider`, so
a broken grammar never aborts an indexing batch.

**Known limit.** `code_chunks` has no `language` column, so
`RetrievalFilters.language` is accepted and ignored. It is reserved for when
indexing covers more than one language.

## Retrieval modes and fusion

`GET /v2/context/retrieve` and
`backend.repository.retrieval.retriever.retrieve()` expose three modes:

| Mode | Backend | Score meaning |
| --- | --- | --- |
| `lexical` | PostgreSQL full-text search | `ts_rank` |
| `vector` | pgvector ANN (HNSW, cosine) | `1 - cosine distance` |
| `hybrid` (default) | both, fused | Reciprocal Rank Fusion score |

Scores are **not comparable across modes** — only the ordering within one
response is meaningful.

### Reciprocal Rank Fusion

Hybrid mode fuses the two ranked id lists with RRF
(`backend/repository/retrieval/fusion.py`): each chunk scores
`Σ weight_i / (k + rank_i)` over the rankings it appears in, where `rank` is
1-based. RRF operates on ranks, not raw scores, which is what lets it combine
`ts_rank` and cosine distance without a normalization step.

| Parameter | Default | Effect |
| --- | --- | --- |
| `k` | `60` (`DEFAULT_RRF_K`, Cormack et al. 2009) | Higher `k` flattens the influence of exact rank position |
| `weights` | equal (`1.0` per ranking) | Per-ranking multiplier, e.g. to favor lexical over vector |

Ties are broken by first-seen order across the input rankings, so fusion is
deterministic for a fixed input.

**Known limit.** `retrieve()` calls `reciprocal_rank_fusion` with the
defaults; `k` and `weights` are tunable in the fusion function but are not yet
threaded through the retriever or the API. Changing them today means calling
`reciprocal_rank_fusion` directly.

### Request parameters

| Parameter | Default | Notes |
| --- | --- | --- |
| `query` | required | Free-text; also embedded in `vector`/`hybrid` mode |
| `mode` | `hybrid` | `lexical` \| `vector` \| `hybrid` |
| `tenant_id` | default tenant | Every query is tenant-scoped |
| `path_prefix` | — | Restrict to a file path prefix |
| `symbol` | — | Exact symbol name match |
| `limit` | `20` (max `100`) | Chunk ids considered **per mode**, before fusion |
| `budget` | — | Max total estimated tokens across results |

`budget` truncates in relevance order — the least relevant snippets are
dropped first, and the single best result is always kept even if it alone
exceeds the budget. Token counts are estimated at ~4 characters per token
rather than with a real tokenizer.

### Embeddings

`vector`/`hybrid` mode embeds the query through the configured
`EmbeddingProvider`. The default is `StubEmbeddingProvider` — deterministic
and offline, which keeps local-first mode working but produces embeddings with
no semantic meaning. **Recall figures measured against the stub provider are
not representative**; swap in a real provider before reading any recall number
as a quality signal.

## Observability

Indexing and context composition emit OpenTelemetry spans
(`backend/observability/tracing.py`):

| Span | Attributes |
| --- | --- |
| `autodev.repository.index` / `.reindex` | `autodev.index.operation`, `file_count`, `chunks_written`, `chunks_deleted`, `autodev.tenant_id` |
| `autodev.context.compose` | `provider_count`, `item_count`, `failed_provider_count` |
| `autodev.context.provider` | `provider_id`, `weight`, `item_count`, `status`, `error_type` |

Both indexing spans and context spans record **counts only**. File paths,
chunk content, retrieved context, and provider exception messages never reach
a span: repository paths can themselves be sensitive, and a provider error
commonly embeds a DSN with credentials. A failing provider's span carries its
exception *type* and an ERROR status whose description is that type.

Provider spans are started on the worker thread with the composition's context
attached, so each span measures the provider's real execution time and stays
diagnosable even when the composer stopped waiting for it at its timeout.

## Recall and latency benchmark

`scripts/benchmark_retrieval.py` runs a labeled query set through every mode
and reports recall@k, MRR, and p50/p95 latency:

```bash
source .venv/bin/activate
python scripts/benchmark_retrieval.py \
  --cases evals/retrieval/cases.json \
  --database-url postgresql://autodev:autodev@localhost:5432/autodev \
  --k 10 --max-p95-ms 300 --min-recall 0.7
```

The cases file is a JSON list of `{"query": str, "relevantChunkIds": [int]}`.
Labels must be curated against the corpus you indexed — recall measured
against generated labels measures nothing.

With `--max-p95-ms` / `--min-recall`, the script exits non-zero when the
hybrid mode misses the threshold, so it can gate a release. The metric
definitions themselves (nearest-rank percentiles, recall@k, MRR) live in
`backend/repository/retrieval/benchmark.py` and are unit-tested offline in
`backend/tests/unit/repository/test_retrieval_benchmark.py`.

**Not yet done.** The benchmark is a standalone CLI; feeding its metrics into
the Evaluation Service (an `EvalSpec` plus a retrieval-metrics evaluator kind,
so retrieval quality shows up in `ScoreSnapshot`s alongside agent evals)
remains the open E7-S3 DoD item — see `docs/v2_platform/phases/e7_context_rag.md`.
No number in this repository has been measured against a live pgvector
instance yet, so the v2.0-beta gate CNF stays unverified.
