# OSS Self-Hosting Guide

This guide documents the current self-hosting paths for AutoDev Architect using only open-source-friendly infrastructure.

---

## Goals of the current slice

- keep the default runtime operable without paid services;
- preserve state outside prompt text via local config and durable storage;
- support both UI-driven and CLI-driven operator workflows;
- offer a first-class local-model path through Ollama.

---

## Supported operating modes

### 1. Deterministic bootstrap mode

Use this mode when you want a fully local setup without any live model dependency.

- `LLM_PROVIDER=stub`
- SQLite-backed durable store
- FastAPI backend
- Next.js frontend
- optional CLI via `python -m backend.cli`

This is the safest initial path for contributors and CI-style smoke testing.

### 2. Local-model mode with Ollama

Use this mode when you want local inference without a hosted provider.

- `LLM_PROVIDER=ollama`
- `OPENAI_MODEL` or runtime config `llm.model` set to an Ollama-served model such as `llama3.1`
- `OLLAMA_BASE_URL` defaults to `http://localhost:11434/v1`
- the backend uses an OpenAI-compatible transport so the same typed runtime config works across providers

Recommended startup flow:

1. Start Ollama locally.
2. Pull the desired model in Ollama.
3. Save the provider/model settings through the web config workspace or the CLI.
4. Start the backend and frontend.

### 3. Hybrid hosted-provider mode

Use this when a hosted model is acceptable for some environments.

- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY` required
- `OPENAI_BASE_URL` optional for compatible gateways/proxies

This mode should remain optional rather than required for core platform operation.

---

## Runtime configuration surfaces

The current repository exposes the same typed runtime state through:

- `GET /config` and `PUT /config`;
- the frontend config workspace;
- `python -m backend.cli config show`;
- `python -m backend.cli config set ...`.

This keeps configuration explicit, reviewable, and file-backed in `autodev.config.json`.

---

## Local startup checklist

### Backend

```bash
source .venv/bin/activate
uvicorn backend.api.main:app --reload
```

### Frontend

```bash
cd frontend
npm run dev
```

### CLI examples

```bash
python -m backend.cli config show
python -m backend.cli plan "Improve OSS self-hosting workflow"
python -m backend.cli repository context --query "config ollama cli"
```

---

## Docker Compose bootstrap

The repository ships a bootstrap Compose stack in `infrastructure/docker-compose.yml`.

Current characteristics:

- backend runs with `LLM_PROVIDER=stub` by default;
- frontend points to the local backend API;
- persistent backend data is stored in the `autodev_data` volume.

This keeps the default Compose story aligned with the OSS-first requirement, even before PostgreSQL/Redis/MinIO are wired into the production path.

---

## Known gaps before production-grade self-hosting

The current 0.6 slice is intentionally incomplete. The next release wave should add:

- PostgreSQL as the primary durable store;
- Redis-backed async execution;
- MinIO-backed artifact storage;
- persisted multi-repository policies;
- Docker sandbox validation;
- OpenTelemetry, Prometheus, Grafana, and Loki integration;
- stronger CI coverage for backend, frontend, docs, and infrastructure.

These items are tracked in [`docs/roadmap.md`](../roadmap.md).
