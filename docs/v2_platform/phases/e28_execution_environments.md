# E28 — Execution Environments & Self-Verification

**Wave:** v2.2 — Concept Integration (gated on E14 sandbox/execution
contracts landing first).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E14 (real execution, sandbox runners), E0 (MinIO artifacts),
E9 (MCP), E22-S5 (evidence bundles)
**Enables:** cheaper harness iterations (E23), E25 (Extension Studio builds
in provisioned envs), UI-change verification evidence (E22/E24 dashboards)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.4,
§18.7.20; RFC-008

## Objective

Evolve execution environments from "a Docker container per validation" to a
governed environment layer: **machine snapshots** (fully provisioned
environment images resumable in seconds), a **tiered isolation policy**
(microVM-class isolation for untrusted/LLM-generated code, Docker retained
for trusted validation), a **browser self-verification runner** that lets
agents verify their own UI/e2e work with recorded evidence, and **code-mode
MCP** (tools exposed as code APIs executed inside the sandbox, loading tool
definitions on demand and filtering data before it reaches model context).

## Key result

A harness iteration on a known repo resumes from a snapshot (deps installed,
services up) instead of re-provisioning; untrusted generated code runs under
the stronger isolation class per policy; a UI task produces a browser
recording + screenshots in its evidence bundle; and an agent task that calls
many MCP tools does so through generated code in the sandbox with measured
context-token usage far below the direct tool-call baseline.

## Prior art (condensed)

Devin machine snapshots (resume a fully provisioned machine), GitHub Copilot
`copilot-setup-steps.yml` (pre-provisioning before the agent starts),
enterprise sandboxing consensus (don't run untrusted LLM-generated code on a
shared kernel; Firecracker ~125ms boot / Kata / gVisor tiers; defense in
depth), Google Antigravity (agents verify UI work in a real browser;
recordings as trust artifacts), Anthropic code-execution-with-MCP (tools as
code APIs; ~98% context-token reduction reported; sensitive data stays in
the execution env), sandboxed-agents-competitive (no measured capability
loss). Sources in RFC-008.

## Stories

### E28-S1 — Machine snapshots & environment resume

Subtasks:
- `E28-S1-T1`: snapshot contract — a named, versioned environment image
  (base image + provisioning steps + repo ref + declared services) built by
  a provisioning run and stored via the artifact store (MinIO-backed);
  content-addressed layers; tenant-scoped.
- `E28-S1-T2`: resume path — sandbox runners (E14-S4) accept a snapshot ref
  and start from it; staleness policy (repo drift vs snapshot) triggers
  rebuild-or-warn per configuration.
- `E28-S1-T3`: `snapshot.*` events + `/v2/snapshots` (register/list/detail,
  §14.1 conventions); snapshot build/GC lifecycle with retention policy.

| Criterion | Detail |
| --- | --- |
| Functional | A harness run resuming from a snapshot skips provisioning (measured setup time vs cold start); a stale snapshot is detected and handled per policy; snapshots listable/inspectable via `/v2` only |
| Non-functional | Snapshot storage quota-bound per tenant; GC never deletes a snapshot referenced by a frozen run (replay, §19) |
| DoR (specific) | RFC-008 accepted; epic ADR (snapshot format & isolation-tier policy) filed; E14-S4 runner contract reviewed |
| DoD (specific) | Resume, staleness, and GC-safety tests; `docs/environments/snapshots.md` |
| Dependencies | E14-S4, E0-S7 (artifacts), E8 |

### E28-S2 — Tiered isolation policy

Subtasks:
- `E28-S2-T1`: isolation classes — declare `trusted` (Docker, current
  SandboxRunner) and `untrusted` (microVM-class: Firecracker/Kata, or gVisor
  where microVMs are unavailable) as runner profiles behind one execution
  contract; class chosen by policy (source of code, execution mode, tenant
  config), not by callers.
- `E28-S2-T2`: policy defaults — LLM-generated code executing with network
  or credential access defaults to `untrusted`; platform-authored validation
  suites stay `trusted`; policy is fail-closed (unknown provenance →
  `untrusted`).
- `E28-S2-T3`: defense-in-depth baseline per class — resource limits,
  network egress controls, no shared credentials in `untrusted`; isolation
  class recorded on every execution for audit (E11 consumes).

| Criterion | Detail |
| --- | --- |
| Functional | The same validation job runs unchanged under either class (contract compatibility); a job with unknown provenance lands in `untrusted`; every execution record names its class |
| Non-functional | `untrusted` overhead measured and documented; self-hosters without KVM get the documented gVisor fallback |
| DoR (specific) | E28-S1 available (classes apply to snapshot resume too); weakness 7 status reviewed |
| DoD (specific) | Class-selection policy tests + contract-compat test; `docs/environments/isolation.md` |
| Dependencies | E14-S4, E28-S1, E11 (audit sink, additive) |

### E28-S3 — Browser self-verification runner

Subtasks:
- `E28-S3-T1`: browser runner profile — headless Chromium available inside
  the sandbox as a declared capability (permissioned via E1 broker);
  driving API exposed to agents as a skill.
- `E28-S3-T2`: verification recipe — for UI-affecting patches, the harness
  can require a browser-verification step: navigate, assert, capture
  screenshots + a recording; artifacts attached to the E22-S5 evidence
  bundle and linked from the traceability graph.
- `E28-S3-T3`: safety rails — browser egress restricted to the
  workspace-served app (no open internet by default); credentials never
  injected into the browser context.

| Criterion | Detail |
| --- | --- |
| Functional | A UI patch's evidence bundle contains screenshots/recording produced by the agent's own verification run; a gate can require browser evidence for UI-classified changes |
| Non-functional | Browser runs under the E28-S2 class policy; egress-restricted by default |
| DoR (specific) | E28-S2 available; E22-S5 evidence format reviewed |
| DoD (specific) | Evidence-attachment + egress-restriction tests; `docs/environments/browser.md` |
| Dependencies | E28-S2, E22-S5, E1, E6 (skill packaging) |

### E28-S4 — Code-mode MCP (tools as code APIs)

Subtasks:
- `E28-S4-T1`: code-mode adapter — MCP servers registered with the platform
  (E9-S4) are additionally projected as generated code APIs (typed client
  modules) available inside the sandbox; the agent writes code that calls
  tools instead of emitting one tool-call message per invocation.
- `E28-S4-T2`: on-demand definition loading — tool-definition modules are
  discovered/loaded when the generated code imports them, keeping tool
  schemas out of model context until needed (progressive disclosure).
- `E28-S4-T3`: in-sandbox data filtering — intermediate results stay in the
  execution environment; only the declared, filtered outputs return to
  model context; context-token usage per task measured against the direct
  tool-call baseline (E26-S1 metrics reused).

| Criterion | Detail |
| --- | --- |
| Functional | A multi-tool task executes through generated code with results equivalent to direct tool calls; unneeded tool schemas never enter context (measured); permission broker still mediates every underlying call |
| Non-functional | Generated clients deterministic for a frozen MCP catalog (ADR-005); measured token reduction documented |
| DoR (specific) | E9-S4 MCP adapter reviewed; E28-S2 class policy available (generated code is `untrusted` by default) |
| DoD (specific) | Equivalence, permission-mediation, and token-measurement tests; `docs/environments/code-mode-mcp.md` |
| Dependencies | E9-S4, E28-S2, E1, E26-S1 (metrics) |

## v1/v2 precursor / starting point

- `backend/validation/sandbox.py::SandboxRunner` (§12.3) and the E14-S4
  runner stories are the execution substrate; E28 adds environment
  durability (snapshots), a second isolation class, and two new runner
  capabilities (browser, code-mode) behind the same contracts.
- Weakness 7 (no isolated per-run execution environment) is closed by
  E14-S4 + E28-S1/S2 together: per-run workspaces that are both provisioned
  fast and isolated proportionally to trust.
- E9-S4 already adapts MCP tools for agents one call at a time; E28-S4 is
  an additive projection, not a replacement — direct tool calls remain for
  simple cases.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for snapshots, isolation classes, browser
      evidence, and code-mode MCP.
- [ ] Epic ADR (snapshot format & isolation-tier policy) filed before
      E28-S1 implementation starts.
- [ ] `snapshot.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
