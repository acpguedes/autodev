# Context retrieval and fusion configuration

`GET /v2/context/retrieve` is the versioned surface over AutoDev's code retrieval
(E7-S3). It returns ranked code snippets for a free-text query, scoped to a tenant.

Retrieval requires PostgreSQL: lexical search uses `ts_rank` and vector search uses
pgvector, both Postgres-only. Against any other store the endpoint answers `501`
(see [ADR-011](../v2_platform/decisions/ADR-011-pgvector-hnsw-index.md)).

## Modes

| `mode` | Ranker | Fusion |
| --- | --- | --- |
| `lexical` | PostgreSQL full-text search (`ts_rank`) | none |
| `vector` | pgvector ANN over embeddings | none |
| `hybrid` *(default)* | both | Reciprocal Rank Fusion |

## Reciprocal Rank Fusion

Hybrid mode combines two rankings whose scores live on incompatible scales — a
`ts_rank` relevance score and a cosine distance. RRF sidesteps normalization entirely
by scoring on **rank position** rather than on the underlying score:

```
score(item) = Σ  weight_r × 1 / (k + rank_r(item))
              r
```

for each ranking `r` the item appears in, where `rank` is 1-based. An item missing
from a ranking simply contributes no term for it.

### Parameters

| Query parameter | Default | Effect |
| --- | --- | --- |
| `fusion_k` | `60` | Smoothing constant. Higher values flatten the influence of exact rank position, so the two rankers agree more and top-1 dominance weakens. Must be positive. |
| `lexical_weight` | `1.0` | Weight of the lexical ranking. |
| `vector_weight` | `1.0` | Weight of the vector ranking. |

`60` is the standard constant from Cormack, Clarke & Buettcher (2009) and is a
reasonable default; it is exposed because the right value depends on how well your
embeddings match your corpus.

All three apply to `hybrid` mode only. In `lexical` and `vector` mode nothing is
fused, so they are accepted and ignored — including values that would be rejected
during fusion.

### Weighting

Weights are relative, not normalized: `(10, 1)` and `(1, 0.1)` produce the same
ordering.

Setting a weight to `0` is meaningful and is **not** the same as switching mode. The
zero-weighted ranker still contributes its candidates to the result set, but
contributes nothing to their score. Use this to widen recall through one ranker while
ranking purely by the other.

### Response

```json
{
  "query": "parse the manifest",
  "mode": "hybrid",
  "fusion": {"k": 60, "lexicalWeight": 1.0, "vectorWeight": 1.0},
  "results": [
    {
      "chunkId": 41, "filePath": "backend/agents/manifest.py", "symbol": "validate_agent_manifest",
      "startLine": 120, "endLine": 168, "content": "...", "score": 0.0325, "source": "hybrid"
    }
  ]
}
```

`fusion` echoes the effective configuration so a caller can tell which knobs produced
a ranking; it is `null` outside hybrid mode. `source` reports which ranker(s) surfaced
each result — `lexical`, `vector`, or `hybrid` for an item both rankers returned.

Scores are RRF scores, not similarities. They are comparable **within** one response
and meaningless across responses or against a threshold.

## Budget truncation

`budget` caps the total estimated token count across returned snippets. Truncation
follows relevance order, so the least relevant results are dropped first; the single
best result is always kept even if it alone exceeds the budget.

`limit` is different and applies earlier: it caps how many chunk ids each underlying
ranker contributes *before* fusion.

## Known limitations

- **No measured recall or latency baseline.** ADR-011 reasons about the HNSW-vs-IVFFlat
  trade-off; it does not measure it. The Beta wave gate (`p95 < 300 ms` plus a recall
  baseline) is unverified because it needs a live pgvector benchmark.
- **Retrieval quality is not evaluated.** The Evaluation Service carries no
  retrieval-shaped metrics, so there is no feedback loop from result quality back into
  fusion configuration. Tuning `fusion_k` and the weights is currently manual.
- **Indexing is Python-only.** The tree-sitter registry holds one language and
  indexing walks `.py` files, so retrieval only ever sees Python.
