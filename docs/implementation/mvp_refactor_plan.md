# AutoDev Architect — MVP Refactor & Enhancement Plan

> Decomposed, part-by-part backlog to take AutoDev Architect from functional skeleton to a
> polished, modular MVP with product-grade UI/UX. Each unit is independently implementable in
> an isolated git worktree and individually mergeable. Execute units one at a time.

## Context

**Goal:** Evolve AutoDev Architect (FastAPI backend + Next.js frontend) into a polished MVP with
**excellent UI/UX**, **useful features**, and **absolute modularity**.

**Decisions:**
- **Persistence:** Introduce a **store abstraction (Repository pattern)**, keep **SQLite default**,
  scaffold an optional Postgres adapter. No forced Postgres/Redis/MinIO migration for the MVP.
- **UI/UX:** Rebuild the frontend on **Tailwind CSS + shadcn/ui** with design tokens, light/dark
  theme, and product-grade components.

---

## Evaluation Summary

**Backend** (`backend/`, ~10k LOC, FastAPI + LangChain/LangGraph):
- 3 working auto-discovery plugin seams: API routers (`backend/api/routers/__init__.py`), CLI
  plugins (`backend/cli_plugins/__init__.py`), agent registry (`backend/agents/registry.py`).
- Persistence is **SQLite-only** (`backend/persistence/database.py`, `backend/plans/store.py`);
  raw SQL, `CREATE TABLE IF NOT EXISTS` + ad-hoc `_ensure_column()` — **no migrations**, no store
  abstraction.
- LLM factory (`backend/llm/factory.py`): `stub` (default) / `openai` / `ollama`, LRU-cached,
  graceful fallback.
- **Modularity breaks:** agent execution order is **hardcoded** in `backend/orchestrator/service.py`
  (`agent_order` + `_build_default_agents`, discovered agents only `setdefault`); skills need
  explicit import to register; agent metadata contracts hardcoded in `backend/agents/contracts.py`.
- **Stubs / incomplete:** `RedisJobQueue` raises `NotImplementedError` (`backend/jobs/queue.py`);
  tree-sitter provider falls back to lexical always
  (`backend/repository/providers/treesitter_provider.py`); dynamic orchestration is opt-in only
  (`AUTODEV_DYNAMIC_ORCH=1`), default `/chat` is linear.
- **Boundary gaps:** no input validation/size limits/rate limiting on `/chat`, `/plan`; **CORS
  hardcoded** to `localhost:3000` (`backend/api/main.py`); unbounded `messages` growth; no
  integration tests.

**Frontend** (`frontend/`, Next.js 14 App Router, React 18):
- **Pure CSS** (`styles/globals.css`, ~695 lines), **no component library**, native `fetch`
  (`lib/api.ts`, `lib/api_ext.ts`), dark-theme only, 1 test file.
- 6 pages: `/` (chat/execution), `/config`, `/agents`, `/plans`, `/skills`, `/patches`.
- **Missing for product-grade UX:** real-time run streaming (console only polls), diff viewer
  (plain `<pre>`), plan approval UI (read-only), run history (`RunHistoryPanel.tsx` exists but
  never rendered), session management, observability dashboards, syntax highlighting, toasts,
  keyboard shortcuts, light/dark toggle, copy/export.

**Infra/docs:**
- `infrastructure/docker-compose.yml` runs backend + frontend only. `terraform/main.tf` is a
  placeholder. CI works. 12 `AUTODEV_*` feature flags scattered. Docs **overclaim** vs. flag-gated
  reality (`docs/architecture/weaknesses_and_strategies.md` is an honest debt log).

---

## Work Units

Phases indicate logical ordering/priority, **not** hard dependencies. *(soft-dep: #N)* notes where
a unit is most naturally built after another.

### Phase 1 — Modularity & Foundations (backend)

**Unit 1 — Store abstraction layer (Repository pattern) + SQLite adapter**
- Files: `backend/persistence/` (new `base.py` protocol + `sqlite_adapter.py`),
  `backend/persistence/database.py`, `backend/plans/store.py`.
- Define `Store`/`SessionRepository`/`RunRepository`/`MessageRepository`/`PlanRepository`
  protocols; move all raw SQL behind SQLite adapters; add a `get_store()` factory keyed off
  `DATABASE_URL`; scaffold a `PostgresStore` that raises a clear "not yet implemented" with TODO.
  Keep SQLite default. No behavior change.

**Unit 2 — Lightweight schema migrations** *(soft-dep: #1)*
- Files: `backend/persistence/migrations/` (new), wired into store init.
- Replace `CREATE TABLE IF NOT EXISTS` + `_ensure_column()` with a tiny versioned migration runner
  (a `schema_version` table + ordered migration callables).

**Unit 3 — Complete the plugin seams ("absolute modularity")**
- Files: `backend/orchestrator/service.py`, `backend/agents/registry.py`,
  `backend/skills/builtin/__init__.py`, `backend/agents/contracts.py`, config module from #4.
- Move `agent_order` and agent construction into config/registry so agents are fully discovered
  (no hardcoded `_build_default_agents`); let discovered agents participate in ordering (not just
  `setdefault`); auto-discover skills via `pkgutil` like routers/CLI; decouple agent metadata
  contracts so a new agent self-declares its output model. Goal: **add an agent/skill by dropping
  a file, no core edits.**

**Unit 4 — Centralized settings + feature-flag module** *(enables #3, #5)*
- Files: `backend/config/settings.py` (new, `pydantic-settings`), replace scattered
  `os.environ`/`os.getenv` reads for the 12 `AUTODEV_*` flags.
- Single typed settings object; document each flag; expose `GET /features` returning the active
  feature matrix.

**Unit 5 — API boundary hardening** *(soft-dep: #4)*
- Files: `backend/api/main.py`, `backend/api/routers/*.py`.
- Pydantic request models with length/size limits on `/chat`, `/plan`, `/repository/context`;
  **env-configurable CORS**; basic rate limiting; consistent error envelope.

### Phase 2 — Backend Features & Robustness

**Unit 6 — Real-time run streaming endpoint (SSE)** *(pairs with #13)*
- Files: `backend/api/routers/orchestration.py` (or new `streaming.py`),
  `backend/orchestrator/service.py` (emit step events).
- Add `GET /sessions/{id}/runs/{run_id}/stream` (Server-Sent Events) emitting per-step
  start/finish/agent-output events.

**Unit 7 — Dynamic orchestration as a first-class path** *(soft-dep: #3)*
- Files: `backend/orchestrator/routing.py`, `backend/orchestrator/graphs.py`,
  `backend/api/routers/orchestration.py`.
- Promote dynamic routing to a supported, documented mode selectable per-request (add request
  field `orchestration_mode`); keep linear as default.

**Unit 8 — Finish RedisJobQueue + async skill execution with timeouts**
- Files: `backend/jobs/queue.py`, `backend/skills/registry.py`.
- Implement the real `RedisJobQueue` (behind `AUTODEV_JOB_BACKEND=redis`, optional dep); add
  timeout/cancellation around skill `run()`.

**Unit 9 — Real tree-sitter symbol extraction**
- Files: `backend/repository/providers/treesitter_provider.py`, `backend/repository/intelligence.py`.
- Implement actual AST-based symbol extraction (functions/classes/imports), lexical fallback when
  `tree_sitter` is absent.

**Unit 10 — Backend integration & API test suite** *(soft-dep: most backend units)*
- Files: `tests/integration/` (new/expanded), `backend/tests/`.
- End-to-end `/chat` → orchestrator → agents → storage round-trip; endpoint tests for every
  router; LLM stub-fallback test; config round-trip test.

### Phase 3 — Frontend Rebuild (Tailwind + shadcn/ui)

**Unit 11 — Frontend design-system foundation** *(others in Phase 3 soft-dep this)*
- Files: `frontend/` — Tailwind config, `postcss`, shadcn/ui init, design tokens, `ThemeProvider`
  (light/dark), root layout/shell, replace `styles/globals.css` base with token layer.
- Ship the new shell with existing pages re-skinned minimally so the app still works.

**Unit 12 — App shell, navigation & primitives** *(soft-dep: #11)*
- Files: `frontend/components/` (sidebar, topbar, breadcrumbs, command palette `Cmd+K`), shadcn
  primitives (button, input, card, dialog, toast, tabs, badge).
- Replace the two ad-hoc layout modes in `ChatLayout.tsx` with one consistent shell across routes.

**Unit 13 — Chat/execution dashboard + real-time streaming UI** *(soft-dep: #11, #6)*
- Files: `frontend/app/page.tsx`, `frontend/components/ExecutionConsolePanel.tsx`,
  `MessageList.tsx`, `lib/api.ts`.
- Redesign main dashboard; consume the SSE stream (#6); progress indicators, copy/export console,
  empty/error states.

**Unit 14 — Patch diff viewer** *(soft-dep: #11)*
- Files: `frontend/app/patches/page.tsx`, new `components/DiffViewer.tsx`.
- Syntax-highlighted, side-by-side/inline unified-diff viewer with copy-to-clipboard.

**Unit 15 — Plan approval UI** *(soft-dep: #11)*
- Files: `frontend/app/plans/page.tsx`, `lib/api_ext.ts`.
- Approve/reject/comment, editable steps, status timeline — wired to `/plans/{id}/approve|reject`.

**Unit 16 — Run history & session management** *(soft-dep: #11)*
- Files: `frontend/components/RunHistoryPanel.tsx` (render it!), `app/page.tsx`, session switcher.
- Session list/switch/rename/delete; run history filtered by status/agent/date.

**Unit 17 — Observability dashboard** *(soft-dep: #11, #4)*
- Files: new `frontend/app/observability/page.tsx`, `lib/api_ext.ts`.
- Consume `GET /metrics` + `GET /features`; run timelines, agent utilization, error rates.

**Unit 18 — Config & registry pages polish + UX niceties** *(soft-dep: #11, #12)*
- Files: `frontend/app/config/page.tsx`, `app/agents/page.tsx`, `app/skills/page.tsx`.
- Rebuild config workspace (validation, tooltips, cancel/discard), polish registries, global
  toasts/notifications, keyboard-shortcut help.

**Unit 19 — Frontend test suite** *(soft-dep: Phase-3 units)*
- Files: `frontend/lib/__tests__/`, new component tests; add `@testing-library/react`, jsdom to
  `vitest.config.ts`.

### Phase 4 — Infra, Docs & DX

**Unit 20 — Full-stack docker-compose profile (opt-in)**
- Files: `infrastructure/docker-compose.yml`, `infrastructure/docker/`.
- Add an opt-in compose **profile** with postgres + redis + minio + ollama wired via settings (#4),
  without changing the lightweight default.

**Unit 21 — Docs reconciliation & feature matrix** *(soft-dep: relevant units)*
- Files: `README.md`, `docs/roadmap.md`, `docs/architecture/*`, new `docs/feature_matrix.md`.
- Replace overclaims with a precise **default vs. optional** feature matrix; document the new
  modularity, settings, streaming, and store abstraction.

**Unit 22 — CI & Makefile hardening**
- Files: `.github/workflows/*`, `Makefile`, `.pre-commit-config.yaml`.
- Coverage gates, a smoke e2e job (boot backend, hit `/health` + one flow), new `make` targets;
  keep `make check` as CI parity.

---

## Round-2 Findings (execution, persistence, agent flow)

Deeper tracing surfaced three concrete problems that motivate Phase 5:

1. **Plan-persistence bug (reproduces the reported "plan not saved").**
   `OrchestratorService.create_plan()` (`backend/orchestrator/service.py:263-278`) writes the plan
   only to `DurableStore.sessions.plan_json` and **never** calls `PlanStore.upsert_plan()`
   (`backend/plans/store.py:106`). The orchestrator has zero references to `PlanStore`, so a
   generated plan never lands in the approvable `plan_documents` table unless the client makes a
   separate `PUT /plans/{id}`. The derived `ExecutionPlan` (`service.py:130`, `build_execution_plan`
   `:384`) is in-memory only — never persisted.
2. **Execution is mocked.** `execute_plan()` (`service.py:412-506`) loops the tasks, stamps each
   `COMPLETED` with fake timestamps, and stores text — **no real work**. It never calls
   `apply_patch()` (`backend/patches/engine.py:52`) or `SandboxRunner.run()`
   (`backend/validation/sandbox.py:51`); those primitives are reachable only via their own
   endpoints, never from the orchestrator. Agents are pure prompt→text
   (`backend/agents/base.py:75-156`) with **no tool-use**. No git integration. Approval does not
   gate execution.
3. **Agent flow is one-pass linear.** Fixed pipeline navigator→…→responder
   (`service.py:213-225`, edges `:688-701`); no retries, no error recovery, no validator→coder
   feedback loop. `SupervisorPolicy` (`backend/orchestrator/routing.py:71-93`) is defined but
   unused; dynamic routing is still linear-per-route and opt-in. Context accumulates with no
   completeness checks.

**Design stance for Phase 5:** real execution stays **safe by default** — dry-run unless
`AUTODEV_ENABLE_PATCH_APPLY=1`, sandboxed/allowlisted commands unless `AUTODEV_ENABLE_SANDBOX=1`,
and **human approval gates that actually block** (honoring the human-in-the-loop principle).

---

## Phase 5 — Real Execution, Persistence Reliability & Effective Agent Flow

**Unit 23 — Reliable plan persistence (fix the "plan not saved" bug)**
- Files: `backend/orchestrator/service.py`, `backend/plans/store.py`,
  `backend/api/routers/plans.py`, `tests/` (regression test).
- In `create_plan()` (and after analysis derives the execution plan), **auto-persist** to
  `PlanStore.upsert_plan()` so every generated plan lands in `plan_documents` as `draft`. Persist
  the derived `ExecutionPlan` (new `execution_plans` table or reuse the store from #1). Make
  persistence failures **loud** (no swallowed exceptions). Add a regression test: `POST /plan` →
  assert retrievable via `GET /plans/{id}`. *(soft-dep: #1)*

**Unit 24 — Real action-execution engine (replace the mock `execute_plan`)**
- Files: new `backend/execution/` (`executor.py`, `actions.py`, `models.py`),
  `backend/orchestrator/service.py`, wires `backend/patches/engine.py` +
  `backend/validation/sandbox.py`.
- An `ActionExecutor` turns execution-plan tasks into typed **actions** (`apply_patch`,
  `run_command`, `write_file`, `read_file`) run through the existing gated primitives, capturing
  **real** stdout/stderr/exit-code/diff. Replace the simulated loop in `execute_plan()` with the
  executor. Safe-by-default. *(soft-dep: #4, #23)*

**Unit 25 — Agent tool-use loop (read→edit→run→observe→iterate)**
- Files: `backend/agents/base.py`, `backend/agents/{coder,devops,validator}/agent.py`,
  new `backend/agents/tools.py`.
- Give execution-capable agents LangChain **tool bindings** (`read_file`,
  `write_file`/`apply_patch`, `run_command`) backed by the #24 executor, with a bounded agentic
  loop (max iterations, per-tool timeout) and full action logging. Planning/analysis agents stay
  tool-free. *(soft-dep: #24)*

**Unit 26 — Git integration**
- Files: new `backend/repository/git.py`, `backend/execution/actions.py`,
  `backend/api/routers/git.py` (new).
- Branch/diff/commit against the target repo (`AUTODEV_PROJECT_ROOT`); produce PR-ready diffs from
  applied patches; expose status/diff via API. Subprocess `git` with the same safety gating.
  *(soft-dep: #24)*

**Unit 27 — Approval gates that actually block execution**
- Files: `backend/orchestrator/service.py`, `backend/api/routers/plans.py`,
  `backend/execution/executor.py`.
- Require an **approved** plan (`PlanStore` status) before `execute_plan()` runs real actions; gate
  risky actions (patch apply, command run) on approval; return a clear `403/409` with the
  pending-approval reason otherwise. *(soft-dep: #23, #24)*

**Unit 28 — Dump / export mechanisms**
- Files: new `backend/export/bundle.py`, `backend/api/routers/export.py` (new),
  `backend/cli_plugins/export.py` (new).
- `GET /sessions/{id}/export` returns a reproducible JSON bundle (plan, plan_document, runs,
  run_steps, messages, artifacts, execution/action logs); `autodev dump <session_id> [--out dir]`
  writes the bundle (and raw artifacts/logs) to disk, with a secret-redaction pass.
  *(soft-dep: #1, #23, #24)*

**Unit 29 — Iterative orchestration with feedback & retries (effective flow)**
- Files: `backend/orchestrator/service.py`, `backend/orchestrator/routing.py`,
  `backend/orchestrator/graphs.py`.
- Wire `SupervisorPolicy` into a real loop: validator-failure → branch back to coder, **bounded**
  iterations, retries with backoff on agent/tool errors, and context-completeness checks before an
  agent runs. Makes the flow adaptive instead of one-pass linear. *(soft-dep: #3, #7, #25)*

**Unit 30 — Execution tracing & live action logs**
- Files: `backend/observability/`, `backend/execution/executor.py`, `backend/api/routers/`
  (extends streaming from #6); frontend touch in `app/page.tsx` / `ExecutionConsolePanel.tsx`.
- Structured per-action trace (action type, command, exit code, duration, diff), streamed over the
  SSE channel (#6) and persisted so it shows up in the dump (#28) and the live console (#13).
  *(soft-dep: #6, #24, #28)*

> **Frontend follow-through (extend Phase-3 units):** Unit 13 console surfaces real action
> logs/exit codes from #30; Unit 15 plan-approval UI drives the #27 gate (approve → enables
> execute); add an "Export / Dump" action (calls #28) to Unit 16 session management.

---

## End-to-End Verification Recipe (per unit)

> Always run inside the venv per `CLAUDE.md`: prefix with `source .venv/bin/activate &&`. Create it
> first if missing (`python -m venv .venv && source .venv/bin/activate && make install`).

- **Backend units (1–10, 20, 22, 23–29):** `make check-backend` (ruff + mypy + `pytest tests backend/tests -q`).
  Smoke: `make run-backend`, then `curl` the affected endpoint (`/health`, `/chat`, new
  `/features` / SSE `/stream`).
- **Execution / persistence units (23–30):**
  - Persistence (#23): `POST /plan`, capture `session_id`, then `GET /plans/{id}` must return the steps.
  - Real execution (#24–27): against a **throwaway repo** with `AUTODEV_PROJECT_ROOT` set, enable
    gates (`AUTODEV_ENABLE_SANDBOX=1`, `AUTODEV_ENABLE_PATCH_APPLY=1`) and confirm a
    `run_command`/`apply_patch` action yields a **real** exit code / file change / git diff — and
    that with gates off it stays dry-run. Confirm #27 blocks execute until the plan is approved.
  - Dump (#28): `autodev dump <session_id> --out /tmp/bundle` produces a JSON bundle + artifacts;
    verify secrets are redacted.
- **Frontend units (11–19):** `make check-frontend` (`lint && typecheck && test && build`). Visual:
  `make run-frontend`, open `http://localhost:3000`, click through the affected flow; verify the
  light/dark toggle and the new component.
- **Integration:** `make docker-up` (or run both locally) and exercise chat → plan → execute,
  confirming streaming/diff/approval as relevant. The `verify` / `run` skills can drive manual e2e.
- **Full CI parity before merge:** `make check`.

---

## Per-Unit Execution Checklist

```
1. Code review — Invoke the `code-review` skill (reports bugs; does not edit). Fix findings.
2. Unit tests — `source .venv/bin/activate && make check-backend` (backend) or `make check-frontend`.
3. End-to-end — Follow the e2e recipe for this unit's category. Skip only if docs-only.
4. Commit & push — Clear message; push branch; `gh pr create` (no Co-Authored-By trailer — project policy).
5. Report — `PR: <url>` or `PR: none — <reason>`.
```

**Conventions:**
- Keep files under 500 lines; new code in `backend/`, `frontend/`, `tests/`, `docs/`, `scripts/`
  (never root). Read a file before editing. Validate input at boundaries.
- Backend: respect the plugin-seam pattern (drop-a-file); use the settings module (#4) instead of
  ad-hoc `os.getenv`; keep SQLite default.
- Frontend: after #11, use Tailwind + shadcn/ui tokens; no new pure-CSS in `globals.css`.
- Never commit secrets/`.env`.
