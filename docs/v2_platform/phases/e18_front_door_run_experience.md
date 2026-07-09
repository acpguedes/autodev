# E18 — Control Center Front Door & Run Experience

**Wave:** Beta
**Status:** Done (5/5 complete, 2026-07-09)
**Depends on:** E15, E16, E17
**Enables:** first-run onboarding for self-hosters; unblocks the proposed E19 visual-parity audit
**Canonical source:** this document (DX epic; not part of the E0–E13 reference
roadmap — motivated by the 2026-07-09 field report below)

## Objective

Make the redesigned Control Center the front door of AutoDev. A user who
starts the platform with one command lands on the prototype-faithful Web UI
(E17 screens) at `http://localhost:3000`; a user or tool that browses the
backend directly at `http://localhost:8000` gets a self-describing, functional
API surface — a service descriptor at `/`, a working self-hosted `/docs` under
the strict Content-Security-Policy, and README guidance that makes "I only see
JSON" impossible to hit by accident. Everything stays API-first
(`docs/architecture/v2_platform_reference.md` §2.13): the backend describes
and points to the UI, it never renders the product UI.

## Key result

`make run` (new target) starts backend + frontend together and the README
quickstart lands the user on `http://localhost:3000` showing the E17 Control
Center. Browsing `http://localhost:8000/` returns a service descriptor (JSON
for API clients, a minimal CSP-clean HTML pointer page for browsers) instead
of 404, and `http://localhost:8000/docs` renders Swagger UI fully offline
under `default-src 'self'`.

## Why now (field diagnosis, 2026-07-09)

A user following the backend-only path (`uvicorn backend.api.main:app` on
`:8000`) and opening that origin in a browser hit, in sequence:

1. **`GET /` → 404.** The FastAPI app in `backend/api/main.py` defines no
   root route, so the platform's primary origin answers "Not Found" and
   nothing points a human toward the Next.js UI on `:3000`.
2. **`GET /docs` → blank page.** `backend/api/security_headers.py`
   (`SecurityHeadersMiddleware`, landed with the E17 security-headers work)
   applies `content-security-policy: default-src 'self'; object-src 'none';
   base-uri 'self'; frame-ancestors 'none'` to every response. FastAPI's
   default Swagger UI loads its JS/CSS from `cdn.jsdelivr.net` **and** boots
   through an inline `<script>` — both blocked by that CSP, so the page
   renders empty. The CDN dependency also breaks `/docs` on offline or
   egress-restricted networks regardless of CSP, which conflicts with the
   project's self-hostable OSS priority.
3. **`GET /config` → raw JSON.** Expected behavior, but with no front door it
   reads as "the frontend is broken" rather than "this is the API".
4. **No single-command run.** `make run-backend` and `make run-frontend` are
   separate targets and the container quickstart (`make container-up`) boots
   the backend only, so the path of least resistance starts half the product.

The redesigned UI itself is already implemented and faithful to the prototype
(`layout_prototype_brainstorm/Autodev Redesing.html`): E15 delivered the
`ds-*` token layer and app shell per ADR-012, E16 the `/v2` control-plane
surfaces, and E17 the Control Center screens (merged to `main` via PR #78).
E18 fixes reachability and self-description, not the screens.

## Stories

Recommended order: S1 → S2 (both touch `backend/api/main.py`; serializing them
avoids merge conflicts) → S3 → S4 → S5. S1, S3, and S4 are mutually
independent and may run in parallel off the epic branch if desired; S5 lands
last because it documents the finished state.

### E18-S1 — Backend API front door (`GET /`)

Branch: `story/e18-s1-api-front-door`

Subtasks:
- `E18-S1-T1`: root route in `backend/api/main.py` returning a JSON service
  descriptor: `name`, `version`, `description`, `ui_url`, `docs_url`,
  `health_url`, `openapi_url`, and `api.v2_base`. `version` must come from
  the same constant passed to `FastAPI(version=...)` (extract a module-level
  constant if it is currently inline — single source of truth).
- `E18-S1-T2`: `ui_url` driven by a new `AUTODEV_UI_URL` setting in
  `backend/config/settings.py`, defaulting to the first entry of the existing
  CORS-origins default so the two never drift; env var documented.
- `E18-S1-T3`: content negotiation — when the `Accept` header prefers
  `text/html` (a human in a browser), return a minimal CSP-clean HTML pointer
  page (no `<script>`, no inline styles, no external assets) linking to the
  UI URL, `/docs`, and `/health`. One paragraph and three links; explicitly
  not a product UI, keeping §2.13 intact.
- `E18-S1-T4`: auth interaction — mirror whatever exemption treatment
  `/health` has today with respect to `require_api_token`
  (`backend/api/security.py`); record the chosen behavior here and pin it
  with a test. **Decision (implemented):** `/` was added to `_PUBLIC_PATHS`,
  exactly like `/health` — the descriptor is discovery metadata and leaks no
  secrets; pinned by `test_root_is_public_when_token_configured`.

| Item | Content |
| --- | --- |
| CF | Browsing `:8000/` in a browser shows a pointer page with a working link to the Control Center; `curl :8000/` returns the JSON descriptor with a correct, env-overridable `ui_url` |
| CNF | HTML variant is CSP-clean under the unchanged `default-src 'self'` policy (no script, no external assets); descriptor leaks nothing sensitive; docstrings + full type hints on every new function |
| DoR | Decision on `/`-vs-`require_api_token` recorded (mirror `/health`); descriptor field list agreed |
| DoD | `backend/tests/test_api_front_door.py` green (descriptor shape, content negotiation, `AUTODEV_UI_URL` override via settings-cache reset, CSP-cleanliness of the HTML variant); no regressions on `/health`, `/config`, `/v2/*` |
| Dependencies | — |

### E18-S2 — Self-hosted API docs under strict CSP

Branch: `story/e18-s2-selfhosted-docs`

Subtasks:
- `E18-S2-T1`: disable the default docs (`FastAPI(docs_url=None,
  redoc_url=None)`; keep the default `openapi_url`). `/redoc` stays disabled
  — vendoring a second doc UI is waste.
- `E18-S2-T2`: vendor pinned `swagger-ui-dist` assets (only
  `swagger-ui-bundle.js`, `swagger-ui.css`, favicon) under
  `backend/api/static/swagger/`, alongside a `VERSION` note and the
  Apache-2.0 license text (record provenance and the pinned version so
  upgrades are auditable). Mount via Starlette `StaticFiles` at `/static`.
- `E18-S2-T3`: serve a hand-written `/docs` HTML page. Do **not** use
  `fastapi.openapi.docs.get_swagger_ui_html` — it emits an inline `<script>`
  initializer that `default-src 'self'` blocks. The page's only script tag is
  `<script src="/static/swagger/swagger-ui-init.js">`, and that committed
  file calls `SwaggerUIBundle({ url: "/openapi.json", dom_id: "#swagger-ui" })`.
  Zero inline script, zero inline style, zero cross-origin fetches.
- `E18-S2-T4`: keep `SecurityHeadersMiddleware` untouched — the goal is to
  comply with the CSP, not to punch holes in it. Documented fallback only if
  Swagger UI proves to need it (it should not: styles it injects via the DOM
  are not blocked by CSP): a route-scoped `style-src 'self' 'unsafe-inline'`
  override for `/docs` only, pinned by a dedicated test.

| Item | Content |
| --- | --- |
| CF | `:8000/docs` renders a working Swagger UI with no network egress, under the unchanged global CSP |
| CNF | Every `src`/`href` in the `/docs` document is same-origin; no inline `<script>` body; assets served with correct content types; security headers still present on `/docs` responses |
| DoR | S1 merged into the epic branch (shared edits to `backend/api/main.py`); swagger-ui-dist version pinned and license noted |
| DoD | `backend/tests/test_api_docs_selfhosted.py` green (same-origin-only asset references, each `/static/swagger/*` asset returns 200, headers present, regression: `cdn.jsdelivr.net` appears nowhere in the `/docs` HTML); `GET /openapi.json` still 200 |
| Dependencies | E18-S1 (ordering only) |

Implementation note: vendored `swagger-ui-bundle.js` is ~1.1 MB in git —
acceptable for an offline-capable OSS project; a download-at-build-time
alternative violates the offline requirement and is rejected.

### E18-S3 — Single-command run experience

Branch: `story/e18-s3-single-command-run`

Subtasks:
- `E18-S3-T1`: `scripts/run_dev.sh` — starts `uvicorn --reload` and
  `npm run dev` concurrently with prefixed log streams, a `trap` that kills
  both on Ctrl-C, and propagation of the first non-zero exit code.
  Shellcheck-clean, English comments.
- `E18-S3-T2`: `make run` (alias `make dev`) invoking the script; Makefile
  help text updated.
- `E18-S3-T3`: container path — `infrastructure/docker-compose.yml` already
  defines a `frontend` service; wire a compose profile (or equivalent Make
  target) so `make container-up-full` boots backend + frontend while
  `make container-up` stays backend-only (existing E0/story workflows and
  `container-test` untouched). Frontend API base URL points at the backend
  service name; backend CORS origins include the compose frontend origin.
- `E18-S3-T4`: README quickstart reshape — the first runnable path becomes
  `make run` → "open http://localhost:3000"; backend-only invocation moves to
  an "API only / headless" subsection that states explicitly: the backend
  serves the API on `:8000`, the UI is the Next.js app on `:3000`, and
  browsing `:8000` shows a service descriptor, not the product UI.

| Item | Content |
| --- | --- |
| CF | On a fresh clone with deps installed, `make run` serves the Control Center at `:3000` and the API at `:8000`; Ctrl-C stops both cleanly; `make container-up-full` boots both containers with working UI→API calls (CORS OK) |
| CNF | `shellcheck scripts/run_dev.sh` clean; `docker compose -f infrastructure/docker-compose.yml config` passes; `make container-up` behavior unchanged |
| DoR | Compose frontend service reviewed (env, ports); log-prefix format agreed |
| DoD | Manual smoke recorded per `../templates/dod_checklist.md` (no pytest/vitest surface for this story); compose config check wired as a lightweight gate (`check-compose` target or part of `make check`); README quickstart leads with the UI path and the ports table is updated |
| Dependencies | — |

Implementation note: the compose frontend service runs `npm install` on boot
(slow first start) — acceptable for the dev profile; a production frontend
image is future work, out of scope here.

### E18-S4 — Shell string i18n

Branch: `story/e18-s4-shell-i18n`

Subtasks:
- `E18-S4-T1`: route the remaining hardcoded shell strings through the
  existing i18n layer (`frontend/lib/i18n/`): "Workspace", "Legacy", "Theme"
  in `frontend/components/shell/SidebarRail.tsx`; "New session" in
  `frontend/components/shell/ContextHeader.tsx`; sweep the shell for any
  others.
- `E18-S4-T2`: add the corresponding dictionary keys for every locale in
  `frontend/lib/i18n/locales.ts` (English + pt-BR today).
- `E18-S4-T3`: dictionary key-parity unit test across locales, protecting
  future additions.

| Item | Content |
| --- | --- |
| CF | Switching locale in the sidebar translates all shell chrome; no user-visible literal strings remain in shell components |
| CNF | Rendered output unchanged in the default locale; `eslint-plugin-i18next` gate extended to the touched files |
| DoR | String inventory of the shell confirmed |
| DoD | Vitest green: key-parity test + SidebarRail/ContextHeader render assertions; lint/typecheck clean |
| Dependencies | — |

### E18-S5 — Docs & progress hygiene

Branch: `story/e18-s5-docs-hygiene`

Subtasks:
- `E18-S5-T1`: README troubleshooting entry — *"I opened localhost:8000 and
  see JSON / 404 / a blank /docs"* → explains the two-process architecture
  and points at `make run` (post-S1/S2 the symptoms change, but the entry
  future-proofs older checkouts and clarifies the model).
- `E18-S5-T2`: remove the empty `frontend/chat-ui/` placeholder directory
  after confirming nothing references it (fix references otherwise).
- `E18-S5-T3`: final `docs/v2_platform/progress.md` narrative pass for E18;
  record the deferred visual-parity audit (proposed E19) in the
  forward-looking section.

| Item | Content |
| --- | --- |
| CF | A new user who hits any of the diagnosed symptoms finds the explanation in README within one search |
| CNF | All new docs in English; progress.md consistent with git history |
| DoR | S1–S4 merged into the epic branch |
| DoD | README section present; no dangling `frontend/chat-ui/` references; progress.md updated |
| Dependencies | E18-S1..S4 |

## Deferred (proposed E19)

A full visual-parity audit of the E17 screens against the prototype
(`layout_prototype_brainstorm/Autodev Redesing.html` — fonts, tokens, spacing,
per-screen interaction details) is deliberately **out of scope**: it is
open-ended QA work without a crisp DoD and would bloat this epic. Propose it
as **E19** with a per-screen checklist derived from ADR-012 and the prototype
`shots/`. Also out of scope: frontend auth, a production frontend build/serve
in compose, and ReDoc.

## Epic exit checklist

- [x] All 5 stories meet the global DoD (`../templates/dod_checklist.md`)
      plus their story-specific DoD above.
- [x] Full `make check` green (backend lint + typecheck + pytest including
      `test_api_front_door.py` and `test_api_docs_selfhosted.py`; frontend
      lint + typecheck + vitest + build).
- [x] `shellcheck scripts/run_dev.sh` (via the dockerized
      `koalaman/shellcheck:stable`) and
      `docker compose -f infrastructure/docker-compose.yml config` pass.
- [x] Recorded manual smoke in the epic PR description: Control Center at
      `:3000` reached via `make run`, plus `curl` output of `GET :8000/`
      (JSON + HTML variants) and the `/docs` page with same-origin assets.
- [x] `docs/v2_platform/progress.md` updated.

Implementation deviations (recorded in the PR): `NEXT_PUBLIC_API_URL` kept as
`http://localhost:8000` in compose (browser-side variable — a service-name URL
would break UI→API calls); the S4 dictionary edits landed in
`frontend/locales/{en,pt-BR}.json` (this doc's `lib/i18n/locales.ts` pointer
predates the dictionary split).
