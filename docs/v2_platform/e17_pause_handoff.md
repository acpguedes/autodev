# E17 — Pause Handoff (Control Center Screens)

**Status: closed (2026-08-20).** E17 — Control Center Screens is **Done (6/6)**
and merged to `main`; every item listed below as pending has since been
delivered. This document is retained as the historical record of the pause, not
as an instruction to resume. For current epic state see
[`progress.md`](progress.md) and
[`phases/e17_control_center_screens.md`](phases/e17_control_center_screens.md).

> Frozen state of epic E17 at the moment of the pause requested by the user.
> All 6 story branches were pushed to `origin`. This document was written to
> resume from that pause.

## Branch status

| Unit | Branch | Status | Commit |
|------|--------|--------|--------|
| S1 Chat execution view | `story/e17-s1-chat-execution-view` | ✅ done | — |
| S2 Plans approval gates | `story/e17-s2-plans-approval-gates` | ⏸ WIP (typecheck broken) | `4c2a40d` |
| S3 Patches review | `story/e17-s3-patches-review` | ✅ done | `42b677a` |
| S4 Sessions & Config | `story/e17-s4-sessions-config` | ⏸ complete (doc-polish only) | `5ddfd81` |
| S5 Extensions hub | `story/e17-s5-extensions-hub` | ⏸ WIP (test/e2e not verified) | `9da6c8b` |
| S6 Flow builder | `story/e17-s6-flow-builder` | ⏸ WIP (e2e broken) | wip pushed |

## Pending items by priority

### S2 — Plans approval gates (most work remaining)

1. **Broken:** 2× `TS2322` in `lib/plans_v2.ts` (lines 43,14 and 46,14).
   `EDITABLE_STEP_STATES`/`REMOVABLE_STEP_STATES` are `ReadonlySet<PlanStepState>` but
   built with `new Set([...])` (inferred as `Set<string>`).
   **Fix:** `new Set<PlanStepState>([...])`. Then re-run `npm run typecheck`.
2. Run `npm run lint`, `npm run test`, `npm run build`, `make check-frontend` — none run yet.
3. Create an e2e spec for `/plans` in `frontend/e2e/` — mock `**/v2/plans/**` via `page.route()`,
   following the pattern of `shell-navigation.spec.ts`; cover load/edit/approve/reject/add/remove/execute.
4. Screen doc (likely `frontend/docs/screens/plans.md`, convention not finalized) + `code-review` skill on the full diff.
5. Clean final commit (squash the wip) and push.
6. ⚠️ **Verify backend:** `plan_approval_v2.py`, `events/catalog.py`, `step_state.py`,
   `test_plan_approval_v2.py` + 2 new backend files appear modified in `git status`
   relative to the epic tip — the worker claimed not to have touched the backend in this segment; confirm
   that nothing is half-finished.
7. Minor hygiene: `handleRemove` in `page.tsx` leaves a stale `true` entry in `stepBusy` after success (harmless).

### S5 — Extensions hub

1. Replace 5 `[role="button"]` locators → `[data-testid="extension-card"]` in
   `frontend/e2e/extensions-hub.spec.ts` (lines ~159–202) — broken by removal of
   `role="button"` from `ExtensionCard`.
2. Re-run `npm run test`: 18 previous failures (axe color-contrast, nested-interactive,
   `navModel.test.ts`) were fixed but **not verified**. Pay special attention to the new
   stretched-button pattern (accessible-name) and the effects of the `pointer-events` restructuring.
3. `make check-frontend` and `npm run e2e` — never run in this effort.
4. Commit/push additional fixes on the same branch.

### S6 — Flow builder

1. Debug the 4 specs in `frontend/e2e/flow-builder.spec.ts` (all failing):
   - Spec 1: `getByRole("heading", { name: "Flows library" })` not found — inspect the real DOM
     via `frontend/test-results/flow-builder-*/error-context.md`; could be markup without a heading role,
     dev server warm-up, or a cached server serving an old `FlowPalette.tsx` (webServer reuses an
     existing server outside CI).
   - Specs 2–4 (`Coder`, `Clear`, `Save` button): timeouts likely cascading from spec 1.
2. Re-run `npm run e2e` until green.
3. `code-review` skill + `make check-frontend` — not run.
4. Screen doc (likely a short addition in `docs/v2_platform/`).
5. Decide whether `NodeInspector.stories.tsx`/`FlowEditor.stories.tsx` are needed.
6. Final commit (non-wip) and push.

### S4 — Sessions & Config (almost nothing)

1. Doc-polish: in `docs/v2_platform/phases/e17_control_center_screens.md`, explicitly flag
   that the reopen-as-chat link `/?sessionId=<id>` from `SessionRow.tsx` **is not yet consumed** by
   `frontend/app/page.tsx` (E17-S1 file). Cross-unit integration gap, not an S4 bug.
2. **Integration action:** `app/page.tsx` needs `useSearchParams`/`sessionId` for the flow
   to work end-to-end — handle at the epic merge or as a fast-follow.
3. Pre-pause verification all green: 111/111 unit, 17/17 e2e, lint/typecheck/build clean.

## Global gotchas

- Playwright: `npx playwright install chromium` **without** `--with-deps` (prompts for sudo password in the sandbox).
- `frontend/test-results/` is **not** gitignored — do not commit (S6 left untracked artifacts in the worktree).
- Token `--ds-fg-3`: measures 4.11:1 against `--ds-bg-2` in dark mode (below the 4.5:1 AA threshold for body text);
  usages were swapped to `text-ds-fg-2` in S5/S6, but the token itself deserves a design audit
  (stale comment in `globals.css` lines 130–133 references a non-existent `frontend/docs/design-tokens.md`).
- `placeholder:text-ds-fg-3` deliberately kept as-is (axe does not flag placeholder contrast).
- No `.claude/settings.json` in the worktrees → no `Co-Authored-By` trailer (correct per repo convention).

## Resume steps (suggested order)

1. Resume S2 (largest pending item) → S6 → S5 → S4 (doc-polish).
2. Merge the 6 story branches into the epic branch (session task #1).
3. Pre-PR gate: save session, 85% check, frontend security audit (task #2).
4. Epic PR to `main`, merge, branch cleanup, local sync (task #3).
5. At merge time: resolve the S1↔S4 gap (`useSearchParams` in `app/page.tsx`).
