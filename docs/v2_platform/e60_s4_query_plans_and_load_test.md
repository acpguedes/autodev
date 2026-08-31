# E60-S4 — Query Plans and Load Test Evidence

DoD evidence for E60-S4-T3 ("`EXPLAIN ANALYZE` review of the hot query paths
... plus a minimum load test establishing explicit limits and SLOs"). All
numbers below were measured against a real PostgreSQL 16 server
(`pgvector/pgvector:0.8.3-pg16`, matching the pinned Compose image), not
estimated: a throwaway container, migrated with this codebase's own
`PostgresStore`, provisioned with a non-superuser `ci_test` role so
Row-Level Security actually applies (mirroring `ci-backend.yml`'s CI
provisioning), and seeded with representative volumes (200 tenants x 500
rows for `run_leases`/`pending_action_decisions`/`execution_environments`,
5,000 vectors for `code_embeddings`). The container was discarded after
measurement; nothing here depends on persistent infrastructure.

## 1. Query plans for hot paths

Every plan below is `EXPLAIN (ANALYZE, BUFFERS)` output, connected as the
same non-superuser role the application itself uses, with
`app.tenant_id` set the way `set_postgres_tenant` sets it in production
(so Row-Level Security is exercised exactly as a real request would see
it, not bypassed).

### 1.1 `QuotaStore.acquire_run_lease` (E51) — existing-lease lookup

```sql
SET app.tenant_id = 'e60-load-tenant-0001';
EXPLAIN (ANALYZE, BUFFERS)
SELECT expires_at, released_at FROM run_leases
WHERE run_id = 'e60-load-tenant-0001-run-0' FOR UPDATE;
```

```
LockRows  (actual time=0.041..0.041 rows=1 loops=1)
  ->  Index Scan using run_leases_pkey on run_leases  (actual time=0.023..0.024 rows=1 loops=1)
        Index Cond: (run_id = 'e60-load-tenant-0001-run-0'::text)
        Filter: (tenant_id = current_setting('app.tenant_id'::text, true))
Execution Time: 0.068 ms
```

Uses the primary key, RLS applied as a post-index filter (a single-row PK
lookup makes any additional index redundant here). Sub-tenth-millisecond.

### 1.2 `QuotaStore.acquire_run_lease` — tenant active-lease count

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*) FROM run_leases
WHERE tenant_id = 'e60-load-tenant-0001' AND released_at IS NULL
  AND run_id != 'x' AND expires_at > now();
```

```
Aggregate  (actual time=0.029..0.029 rows=1 loops=1)
  ->  Index Scan using idx_pg_run_leases_tenant on run_leases  (actual time=0.024..0.025 rows=1 loops=1)
        Index Cond: ((tenant_id = ...) AND (released_at IS NULL) AND (expires_at > now()))
Execution Time: 0.062 ms
```

Confirms the E50 tenant-first composite index (`tenant_id, released_at,
expires_at`) is used exactly as designed — every predicate except `run_id
!=` is satisfied by the index itself.

### 1.3 `PolicyStore.list_pending_decisions` (E53) — tenant + status

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... FROM pending_action_decisions
WHERE tenant_id = 'e60-load-tenant-0001' AND status = 'pending';
```

```
Index Scan using idx_pg_pending_action_decisions_tenant_status on pending_action_decisions
  (actual time=0.028..0.036 rows=50 loops=1)
  Index Cond: ((tenant_id = ...) AND (status = 'pending'::text))
Execution Time: 0.078 ms
```

50 matching rows returned directly from the tenant+status composite index
against 100,050 total rows in the table — no heap rescan needed beyond the
returned rows.

### 1.4 `PolicyStore.list_due_pending_decisions` (E53) — cross-tenant expiry sweep

This method deliberately does not set `app.tenant_id` (its own docstring:
"there is no single tenant to scope this query to"). Run unscoped through
the application's own role, it correctly returns **zero rows** — proof of
the fail-closed RLS contract E60-S2 depends on:

```
Index Scan using idx_pg_pending_action_decisions_tenant_run on pending_action_decisions
  (actual time=0.004..0.004 rows=0 loops=1)
  Index Cond: (tenant_id = current_setting('app.tenant_id'::text, true))
```

Run instead through the bootstrap superuser (the administrative/`BYPASSRLS`
path the method's docstring says this sweep actually requires), the intended
index is used and the real cross-tenant result set comes back:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT decision_id FROM pending_action_decisions
WHERE status = 'pending' AND expires_at <= now();
```

```
Bitmap Heap Scan on pending_action_decisions  (actual time=0.506..3.530 rows=11200 loops=1)
  Recheck Cond: ((status = 'pending'::text) AND (expires_at <= now()))
  ->  Bitmap Index Scan on idx_pg_pending_action_decisions_status_expiry
        (actual time=0.400..0.400 rows=11200 loops=1)
Execution Time: 3.808 ms
```

3.8ms to scan and return 11,200 of 100,050 rows via the dedicated
status+expiry index — confirms the E53 expiry index is the one actually
chosen by the planner, not a coincidental fallback.

### 1.5 `EnvironmentStore.list_expired_active` (E54) — tenant + status + expiry

```sql
SET app.tenant_id = 'tenant-0050';
EXPLAIN (ANALYZE, BUFFERS)
SELECT environment_id FROM execution_environments
WHERE tenant_id = 'tenant-0050' AND status = 'active'
  AND expires_at <= now() + interval '1 hour';
```

```
Index Scan using idx_pg_execution_environments_tenant_status on execution_environments
  (actual time=0.021..0.038 rows=125 loops=1)
  Index Cond: ((tenant_id = ...) AND (status = 'active'::text) AND (expires_at <= ...))
Execution Time: 0.064 ms
```

### 1.6 HNSW vector similarity search (`code_embeddings`, E7/E48)

```sql
SET app.tenant_id = 'tenant-0000';
EXPLAIN (ANALYZE, BUFFERS)
SELECT chunk_id FROM code_embeddings
WHERE tenant_id = 'tenant-0000'
ORDER BY embedding <=> (SELECT embedding FROM code_embeddings
                         WHERE tenant_id = 'tenant-0000' LIMIT 1)
LIMIT 10;
```

```
Index Scan using idx_pg_code_embeddings_hnsw on code_embeddings
  (actual time=0.211..0.213 rows=10 loops=1)
  Order By: (embedding <=> $0)
  Filter: (tenant_id = 'tenant-0000'::text)
Execution Time: 0.285 ms
```

The HNSW index is used for the nearest-neighbor ordering itself (not just a
pre-filter), confirming ADR-011's index choice holds under RLS.

### Summary

| Query | Intended index | Used? | Execution time |
| --- | --- | --- | --- |
| Lease PK lookup | `run_leases_pkey` | yes | 0.068 ms |
| Lease tenant active-count | `idx_pg_run_leases_tenant` | yes | 0.062 ms |
| Pending decisions by tenant+status | `idx_pg_pending_action_decisions_tenant_status` | yes | 0.078 ms |
| Due-decision sweep (admin path) | `idx_pg_pending_action_decisions_status_expiry` | yes | 3.808 ms |
| Expired environments by tenant | `idx_pg_execution_environments_tenant_status` | yes | 0.064 ms |
| HNSW nearest-neighbor | `idx_pg_code_embeddings_hnsw` | yes | 0.285 ms |

Every hot path from E50/E53/E54 uses its intended index; no sequential scan
appears on any tenant-scoped or status/expiry-scoped hot path.

## 2. Load test: bounded pool under concurrent writers

Methodology: `QuotaStore.acquire_run_lease` (E51's advisory-lock-guarded
write path, the most contended write in the E51-E55 surface) run
concurrently through a bounded `PostgresConnectionManager` pool
(`max_size=10`, `timeout_seconds=2.0`), 500 operations per scenario, against
one fresh tenant per run so results are not skewed by pre-seeded rows.

| Concurrency | Throughput (ops/s) | p50 | p95 | p99 | max | Errors | Pool-exhausted |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | 185.2 | 39.9 ms | 53.3 ms | 114.4 ms | 134.1 ms | 0 | 0 |
| 20 | 146.2 | 124.2 ms | 224.0 ms | 238.3 ms | 276.2 ms | 0 | 0 |
| 50 | 153.7 | 305.8 ms | 464.1 ms | 467.1 ms | 496.9 ms | 0 | 0 |
| 100 | 203.7 | 480.3 ms | 507.3 ms | 515.5 ms | 517.9 ms | 0 | 0 |

At every concurrency level up to **10x the pool's configured `max_size`**,
every operation still completed successfully inside the 2-second pool-wait
budget: callers queue for a checkout and pay latency, they do not fail.
Zero `PostgresPoolExhaustedError`s were raised in any scenario.

### Stated SLOs (from measurement, not assumption)

- **At <= pool capacity (concurrency <= `max_size`)**: p95 lock-guarded
  write latency stays under **60 ms** (measured 53.3 ms at concurrency 8).
- **At up to 10x pool capacity**: the system degrades gracefully to p95 <=
  **510 ms** rather than failing; zero pool-exhaustion errors at the default
  2-second `AUTODEV_POSTGRES_POOL_TIMEOUT_SECONDS`.
- **Statement timeout budget** (`AUTODEV_POSTGRES_STATEMENT_TIMEOUT_MS`,
  default 30,000 ms) and **lock timeout** (`AUTODEV_POSTGRES_LOCK_TIMEOUT_MS`,
  default 5,000 ms) both sit at least two orders of magnitude above the
  measured p99 (515.5 ms at 10x load) — the E60-S3-T1 defaults do not risk
  cutting off legitimate contention at any load level measured here.

### Pool exhaustion is real and correctly typed

A second, deliberately undersized scenario (`max_size=4`,
`timeout_seconds=0.05`, 20 concurrent operations each holding their
connection for 300 ms via `pg_sleep`) confirms
`PostgresPoolExhaustedError` fires under genuine backpressure rather than
only in unit tests: **4 operations succeeded, 16 raised
`PostgresPoolExhaustedError`** — exactly the pool's configured capacity,
no more, no fewer.

## 3. Interpretation for operators

- Size `AUTODEV_POSTGRES_POOL_MAX_SIZE` to the sustained concurrent-write
  rate you actually expect; the measurements above show the pool degrades
  to added latency, not errors, under moderate oversubscription — but that
  latency is visible via `autodev.postgres.pool.wait_duration` and the
  `postgres_pool` readiness check (E60-S4-T2) well before it becomes an
  incident.
- The `AutoDevPostgresPoolSaturated` and `AutoDevPostgresDeadlockRateRising`
  alerts (`infrastructure/observability/prometheus-rules.yml`) and their
  runbook procedures (`docs/v2_platform/runbooks/e11_incident_response.md`
  §3.4/§3.5) are the escalation path once these SLOs are breached in
  production.
