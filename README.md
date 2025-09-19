# AutoDev Architect

Quickstart guide for running the project in development mode.

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm (or another compatible package manager such as `pnpm` or `yarn`)

## Setting up and running the backend (FastAPI)

1. Create and activate a virtual environment (optional but recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\\Scripts\\activate   # Windows
   ```

2. Install the dependencies (including LangChain, LangGraph, and the client for your chosen LLM):

   ```bash
   pip install -r backend/requirements.txt
   ```

3. Start the API server:

   ```bash
   uvicorn backend.api.main:app --reload
   ```

   The API will be available at `http://localhost:8000`. The `/docs` endpoint exposes the interactive documentation.

### Configuring the LLM

The backend uses LangChain and LangGraph to coordinate the agents. By default it runs a fully deterministic stub implementation—useful for local development without extra costs. To use a real LLM, configure the following environment variables before starting the server:

- `LLM_PROVIDER`: set to `openai` to use `ChatOpenAI` via `langchain-openai` (default: `stub`).
- `OPENAI_API_KEY`: required API key for the OpenAI provider.
- `OPENAI_MODEL`: the desired model (for example, `gpt-4o-mini`).
- `OPENAI_TEMPERATURE`: sampling temperature (optional, default `0.2`).
- `OPENAI_BASE_URL`: alternate base URL if you are targeting a compatible endpoint.

Example configuration for the official OpenAI provider:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o-mini"

uvicorn backend.api.main:app --reload
```

With these variables defined, the agents will call the model through LangChain; if any credential is missing the backend automatically falls back to the built-in static responses.

## Setting up and running the frontend (Next.js)

1. In another terminal, install the dependencies:

   ```bash
   cd frontend
   npm install
   ```

2. Start the development server:

   ```bash
   npm run dev
   ```

3. The UI will be reachable at `http://localhost:3000`.

> **Tip:** By default the frontend targets the browser's current origin when calling the backend (for example, `https://your-domain`). This works automatically when the frontend and API share the same domain or reverse proxy. If the backend lives on a different host—or you need an absolute URL during server-side rendering—set `NEXT_PUBLIC_API_URL` to the full origin (without a trailing slash) before starting the frontend.

## Quick tests

To validate the orchestrator's main flow, run:

```bash
pytest tests/backend/test_orchestrator.py
```
