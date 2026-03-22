# Project: **AutoDev Architect**

**AutoDev Architect** is an open source platform for **AI-powered software planning, repository analysis, patch generation, validation, and autonomous project evolution**.

The project is designed to be a credible, self-hostable alternative in the category of GenAI developer tools alongside cloud-assisted coding systems, while remaining aligned with OSS values:

- transparency;
- reproducibility;
- extensibility;
- user control;
- self-hosted operation;
- provider flexibility.

---

## Mission

Build an open source control plane for software engineering agents that can help teams **create, improve, validate, and operate software systems safely**.

Instead of acting like a black-box chatbot that emits code snippets, AutoDev Architect aims to become an **auditable engineering workflow system** that combines planning, code intelligence, patching, validation, and human approval.

The current implementation already includes a bootstrap durable control plane, persisted workflow-step history, configurable stub/OpenAI agent execution, a persisted runtime configuration layer for LLM and repository/workspace selection, a dedicated frontend config workspace, a first repository-context retrieval API for ranked file discovery, post-analysis execution-plan generation with sequential task execution, and published typed agent metadata contracts for downstream machine-readable consumers.

---

## Core problem

Most code-generation assistants are optimized for local suggestions or opaque cloud workflows. Teams that need stronger controls often lack:

- complete traceability of AI-driven changes;
- self-hosting options;
- structured approval workflows;
- repository-aware planning and patching;
- integration between code generation and validation;
- reusable execution policies for engineering organizations.

AutoDev Architect addresses this by treating AI-assisted development as a **multi-stage software delivery pipeline**, not just a prompt-response interface.

---

## Product scope

The platform should support two primary modes.

### 1. Greenfield creation
Users can describe a new service, product, or technical system and receive:

- architecture proposals;
- implementation plans;
- code scaffolding;
- tests;
- CI/CD configuration;
- infrastructure templates;
- documentation.

### 2. Existing project evolution
Users can describe changes to an existing repository and receive:

- repository navigation results;
- impact analysis;
- patch proposals;
- validation reports;
- documentation updates;
- pull request-ready outputs.

---

## Target user profiles

- Open source maintainers.
- Platform engineering teams.
- Internal developer platform teams.
- Startups that want self-hosted AI engineering workflows.
- Security-conscious organizations that cannot depend entirely on closed SaaS tooling.
- Research teams experimenting with agentic software engineering.

---

## Product differentiators

### 1. Open source and self-hostable
The project should be deployable using open source infrastructure and local models when required.

### 2. Patch-based change model
The system should prefer **minimal, reviewable diffs** over full rewrites.

### 3. Human approval workflow
Plans, patches, and sensitive actions should support approval gates.

### 4. Repository intelligence
The platform should combine syntax-aware indexing, lexical search, semantic search, and metadata extraction.

### 5. Execution + validation loop
Changes are not complete until they are executed in isolation and validated.

### 6. Full-run observability
Every run should be inspectable across prompts, outputs, validations, approvals, costs, and artifacts.

---

## Functional pillars

1. **Planning**
   - Decompose user intent into executable work.
   - Track assumptions, risks, and acceptance criteria.

2. **Navigation**
   - Understand repository structure.
   - Locate relevant files, symbols, tests, and dependencies.

3. **Analysis**
   - Compare intent with the current codebase.
   - Produce structured change plans and impact summaries.

4. **Architecture**
   - Propose system-level decisions, patterns, and contracts.

5. **Coding**
   - Produce localized patches and supporting tests.

6. **DevOps**
   - Generate delivery, container, and deployment assets.

7. **Validation**
   - Execute checks and feed failures back into the workflow.

8. **Governance**
   - Enforce approvals, policies, permissions, and auditability.

---

## Non-functional requirements

A complete implementation of AutoDev Architect must satisfy these requirements:

- **Persistence**: runs and sessions survive restarts.
- **Isolation**: execution occurs in controlled workspaces.
- **Observability**: traces, metrics, and logs are first-class concerns.
- **Security**: support least privilege and explicit policy controls.
- **Provider portability**: allow hosted or local models.
- **Extensibility**: agent roles and repository policies can evolve without rewriting the platform.
- **Cost control**: support local inference and intelligent routing.
- **Reproducibility**: every patch and validation result can be reproduced.

---

## Open source stack direction

To preserve independence from paid infrastructure, the project should prioritize:

- **PostgreSQL** for persistent state and system of record;
- **pgvector** for semantic memory and embeddings;
- **Redis** for queues, cache, and distributed coordination;
- **MinIO** for artifact storage;
- **tree-sitter** for code parsing;
- **FastAPI** and **Next.js** for the application layer;
- **Docker** and **Kubernetes** for execution and deployment;
- **OpenTelemetry + Prometheus + Grafana + Loki** for observability;
- **vLLM** or **Ollama** for local model deployment paths.

---

## Why this project matters

There is a growing need for open systems that bring the power of AI coding tools into environments where teams need:

- visibility instead of black boxes;
- process integration instead of prompt fragments;
- policies and approvals instead of ad hoc edits;
- self-hosting instead of vendor lock-in;
- end-to-end engineering workflows instead of isolated suggestions.

AutoDev Architect should become a reference implementation for **open, inspectable, and extensible GenAI software engineering workflows**.
