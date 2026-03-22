# Stack Decisions

This document records the recommended stack for AutoDev Architect and the rationale behind each choice.

---

## Selection criteria

The stack was selected to optimize for:

- open source availability;
- self-hosting;
- maturity and ecosystem fit;
- compatibility with Python and web-native workflows;
- support for asynchronous execution;
- repository indexing and semantic retrieval;
- low operational fragmentation.

---

## Backend and orchestration

### FastAPI
**Chosen for:** API and control plane.

Why:
- excellent Python ecosystem fit;
- async-friendly;
- strong typing with Pydantic;
- good DX and docs generation.

### LangGraph
**Chosen for:** workflow and agent orchestration.

Why:
- supports explicit graph-based execution;
- better fit than ad hoc chains for multi-step workflows;
- allows state propagation and branching.

Constraint:
- business state and persistence should remain outside prompts and in application storage.

---

## Persistent state and memory

### PostgreSQL
**Chosen for:** primary system of record.

Why:
- mature, reliable, open source;
- relational model fits sessions, runs, approvals, events, metadata;
- rich indexing and transactional semantics;
- can centralize multiple operational concerns.

### pgvector
**Chosen for:** semantic memory and retrieval.

Why:
- keeps vector retrieval close to the primary data model;
- reduces operational overhead compared to a separate vector DB in early and mid-stage deployments;
- sufficient for many repository intelligence use cases.

### Redis
**Chosen for:** queueing, cache, locks, and ephemeral coordination.

Why:
- industry standard;
- easy to operate;
- strong fit for async job systems and transient state.

---

## Artifacts and object storage

### MinIO
**Chosen for:** artifact storage.

Why:
- open source and self-hostable;
- S3-compatible;
- good fit for logs, patch bundles, test reports, and generated assets.

---

## Queue and background processing

### Preferred option: Celery + Redis
Why:
- mature ecosystem;
- well understood by many teams;
- suitable for long-running and retryable jobs.

### Simpler option: ARQ + Redis
Why:
- lower complexity;
- async-native Python model;
- good if the platform stays lean.

### Recommendation
Start with **ARQ** for a lighter control plane if the team is small and runtime complexity is moderate. Move to **Celery** only if advanced routing and ecosystem integrations are needed.

---

## Repository intelligence

### tree-sitter
**Chosen for:** AST parsing and syntax-aware extraction.

Why:
- language-aware and fast;
- strong ecosystem across popular languages;
- useful for symbols, scopes, and code chunking.

### ripgrep
**Chosen for:** lexical repository search.

Why:
- extremely fast;
- ideal for candidate narrowing before semantic ranking.

### PostgreSQL FTS
**Chosen for:** indexed lexical search persistence.

Why:
- avoids adding another search cluster too early;
- works well for docs, configs, and symbol metadata.

---

## Frontend and UX

### Next.js
**Chosen for:** Web UI.

Why:
- mature React framework;
- good fit for dashboards, streaming UIs, and auth integration;
- flexible deployment.

### Future CLI
**Chosen for:** operational and developer automation workflows.

Why:
- many engineering users prefer terminal-first interaction;
- useful for CI hooks and repository-local operations.

---

## Execution sandbox

### Docker
**Chosen for:** isolated execution workspaces.

Why:
- well known and portable;
- easy local development path;
- supports reproducible environments.

### Kubernetes
**Chosen for:** production scaling and multi-tenant execution.

Why:
- standard option for isolated workers and operational scaling;
- useful when sandbox runners and queues grow.

---

## Observability

### OpenTelemetry
**Chosen for:** tracing instrumentation standard.

### Prometheus
**Chosen for:** metrics collection.

### Grafana
**Chosen for:** dashboards.

### Loki
**Chosen for:** logs.

Why this set:
- open source;
- cohesive ecosystem;
- broad community adoption.

---

## Model provider strategy

### First-class support should include:
- local models through Ollama or vLLM;
- hosted models when explicitly configured.

### Why this matters
The platform must remain useful without forcing a paid provider. Local operation is a strategic differentiator for the project.

---

## What we are intentionally not choosing right now

### Separate vector DB by default
Examples: Qdrant, Weaviate, Milvus.

Reason:
- useful later for scale, but avoid early operational sprawl;
- PostgreSQL + pgvector is sufficient for initial architecture.

### Kafka or NATS as mandatory core dependency
Reason:
- powerful, but unnecessary complexity in early versions;
- Redis is enough for the first strong platform milestone.

### Elasticsearch/OpenSearch as mandatory search layer
Reason:
- excellent at scale, but avoid adding another cluster until repository intelligence requirements clearly justify it.

---

## Final recommendation summary

- **Backend**: FastAPI
- **Workflow**: LangGraph
- **Primary DB**: PostgreSQL
- **Vector / memory**: pgvector
- **Queue / cache / locks**: Redis
- **Artifacts**: MinIO
- **Parsing**: tree-sitter
- **Search**: ripgrep + PostgreSQL FTS
- **Frontend**: Next.js
- **Sandbox**: Docker
- **Production orchestration**: Kubernetes
- **Observability**: OpenTelemetry + Prometheus + Grafana + Loki
- **Local model path**: Ollama or vLLM

