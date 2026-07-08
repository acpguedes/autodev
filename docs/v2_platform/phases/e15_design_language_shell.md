# E15 — Frontend Redesign: Design Language & App Shell

**Wave:** Beta
**Status:** In progress (2/4 complete)
**Depends on:** E10
**Enables:** E16 (partially — E16's endpoints back the shell's live status
surfaces, but E16 does not require E15 to land first), E17, E14-S5 (the
governed-execution Web UX consumes the execution-panel slot introduced here)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.9

## Objective

Replace AutoDev Architect's current single-shell, dark-only, partially-legacy
frontend with the "Execution Control Center" design language and app shell
from the redesign prototype: a warm-paper/charcoal token system, a 3-region
shell (sidebar rail, contextual header, dismissible execution panel), full
migration off legacy CSS onto the token/Radix `components/ui` kit, and an
i18n foundation with English as the default locale and pt-BR as the first
translation.

## Key result

Every route in `frontend/app/` renders inside the new Execution Control
Center shell, styled exclusively from versioned v2 design tokens (no legacy
`styles/globals.css` classes remain in application code), with all
user-visible copy sourced from locale files defaulting to English, while
keeping WCAG 2.2 AA conformance.

## Stories

### E15-S1 — Design tokens v2 (prototype design language)

**Status:** Done (2026-07-08). Additive `--ds-*` token layer (warm-paper
light / charcoal dark, iris accent, status/diff triads, radius + shadow
scales) landed in `styles/globals.css` with `--ds-token-version` bumped to
`2.0.0`; Newsreader / Instrument Sans / JetBrains Mono wired via
`next/font/google`; `tailwind.config.ts` `ds` namespace, `design-tokens.md`
v2 reference with the WCAG 2.2 AA contrast audit, a Vitest token guard, and
a Storybook token showcase added. Three light status colors nudged 1–2
lightness points for AA; all pairs verified.

Subtasks:
- `E15-S1-T1`: define the v2 color system — warm-paper light theme
  (`#faf8f4` base) and charcoal dark theme (`#100f12` base), iris accent
  (`#5a4fe0` light / `#8e88ff` dark), low-saturation success/warn/danger
  triads, and diff add/del tints, as HSL custom properties following the
  existing `.dark`/`.light` split in `styles/globals.css`.
- `E15-S1-T2`: define the v2 typography system — Newsreader (serif display),
  Instrument Sans (UI body/labels), JetBrains Mono (code/diff/log content) —
  plus an updated radius and shadow scale, extending `styles/globals.css`
  token declarations and `tailwind.config.ts` theme mappings.
- `E15-S1-T3`: bump `--ds-token-version` in `styles/globals.css`, update
  `frontend/docs/design-tokens.md` (currently version `1.0.0`) to document
  every new/changed token, and refresh Storybook stories under
  `components/ui/*.stories.tsx` to render against the new palette/type scale.

| Item | Content |
| --- | --- |
| CF | Warm-paper and charcoal themes render with the specified base/accent colors; typography tokens map Newsreader/Instrument Sans/JetBrains Mono to the correct usage classes; `design-tokens.md` documents every token at the bumped version |
| CNF | WCAG 2.2 AA contrast and focus retained in both themes; no visual regression in existing Storybook stories beyond the intended palette/type change |
| DoR (specific) | Prototype design language reviewed in `layout_prototype_brainstorm/Autodev Redesing.html` and the color/type swatches in `layout_prototype_brainstorm/Frontend redesign proposal.zip` (`shots/`); current token baseline (`frontend/docs/design-tokens.md`, version `1.0.0`) read |
| DoD (specific) | Storybook published with updated tokens; a11y contrast audit re-run with no new blocking violations; `frontend/docs/design-tokens.md` updated with version bump and changelog entry |
| Dependencies | E10-S1 |

### E15-S2 — Execution Control Center shell

**Status:** Done (2026-07-08). Three-region shell — 250px sidebar rail
(brand, workspace switcher, primary nav with count badges, provider status,
theme toggle), 64px contextual header (view title/subtitle, repo chip,
panel toggle, "+ New session"), dismissible 400px execution panel with
persisted open/closed state — wired as the single layout for all
`frontend/app/` routes; `ChatLayout` retired; Playwright e2e navigation
suite and axe audit of the three regions green; shell documented via
Storybook stories.

Subtasks:
- `E15-S2-T1`: build the 250px sidebar rail — brand block, workspace
  switcher, primary nav (Chat / Plans / Patches / Flows / Sessions / Config /
  Extensions) with per-item count badges, provider status card, and theme
  toggle — replacing `components/ChatLayout.tsx`'s `sidebar` layout mode.
- `E15-S2-T2`: build the 64px contextual header — per-view title/subtitle,
  active-repo chip, execution-panel toggle, and a "+ New session" primary
  action.
- `E15-S2-T3`: build the dismissible 400px right execution panel slot (open/
  closed state, keyboard-dismissible, reserved for live execution output
  consumed later by E14-S5 and the E17 screens).
- `E15-S2-T4`: wire the new shell as the single layout for every route under
  `frontend/app/`, retiring `ChatLayout`'s `"focus"` layout mode once all
  call sites migrate.

| Item | Content |
| --- | --- |
| CF | All 9 routes render inside the 3-region shell; sidebar nav badges reflect live counts; execution panel opens/closes via the header toggle and is keyboard-dismissible; "+ New session" is reachable from every view |
| CNF | WCAG 2.2 AA keyboard navigation across all three regions; shell layout has no cumulative-layout-shift regression versus current `ChatLayout`; execution panel state persists per session |
| DoR (specific) | E15-S1 tokens available; current `components/ChatLayout.tsx` (`sidebar`/`focus` modes, `sidebar-nav`, `sidebar-brand`) reviewed as the v1 precursor; shell wireframe cross-checked against `layout_prototype_brainstorm/Autodev Redesing.html` and screenshots in `layout_prototype_brainstorm/Frontend redesign proposal.zip` (`shots/`) |
| DoD (specific) | e2e navigation test across all routes in the new shell; a11y audit of the three regions; shell usage documented (component doc or Storybook) |
| Dependencies | E15-S1 |

### E15-S3 — Legacy CSS migration

Subtasks:
- `E15-S3-T1`: inventory every legacy `styles/globals.css` class still
  consumed by `app/page.tsx` (dashboard), `app/config/page.tsx`,
  `app/plans/page.tsx`, `app/patches/page.tsx`, `app/agents/page.tsx`, and
  `app/skills/page.tsx`.
- `E15-S3-T2`: rewrite each of those pages to compose the token-driven
  `components/ui` kit (currently 12 primitives: `badge`, `breadcrumb`,
  `button`, `card`, `dialog`, `input`, `select`, `skeleton`, `table`, `tabs`,
  `toast`, `toaster`, plus their Storybook stories) instead of legacy
  classes.
- `E15-S3-T3`: remove now-unused legacy shell tokens and rules from
  `styles/globals.css` (currently ~840 lines, mixing legacy and Design
  System-era tokens) once no page references them.

| Item | Content |
| --- | --- |
| CF | The 6 legacy-styled pages render exclusively from `components/ui` + design tokens; no application code references removed legacy classes |
| CNF | No visual functional regression on the migrated pages; `styles/globals.css` line count net-decreases after legacy rule removal; WCAG 2.2 AA retained |
| DoR (specific) | E15-S1 tokens and E15-S2 shell available; legacy class inventory from `E15-S3-T1` complete |
| DoD (specific) | Per-page before/after Storybook or screenshot comparison; a11y re-audit; no remaining `grep` hits for the removed legacy class names in `app/` or `components/` |
| Dependencies | E15-S1, E15-S2 |

### E15-S4 — i18n foundation (en default, pt-BR)

Subtasks:
- `E15-S4-T1`: introduce locale infrastructure (routing/provider strategy
  for Next.js 14 App Router) with English (`en`) as the default locale and
  `pt-BR` as the first translation, per the language decision recorded in
  RFC-006.
- `E15-S4-T2`: externalize all UI copy currently hardcoded and mixed
  pt-BR/English — confirmed present today in `app/page.tsx`,
  `components/ChatLayout.tsx`, and `components/ExecutionConsolePanel.tsx` —
  into locale resource files.
- `E15-S4-T3`: add a locale switcher surfaced from the E15-S2 sidebar rail
  and a CI/lint check that flags new hardcoded, non-externalized UI strings.

| Item | Content |
| --- | --- |
| CF | The app renders fully in English by default; switching locale renders the pt-BR translation with no missing-key fallback text visible; every string previously hardcoded in the 3 identified files is externalized |
| CNF | Locale switch requires no full page reload where technically avoidable; missing-translation fallback never surfaces a raw key to the user; WCAG 2.2 AA `lang` attribute correctness per locale |
| DoR (specific) | RFC-006 (UI language decision: English default + pt-BR via i18n) approved; E15-S2 sidebar rail available to host the locale switcher; current mixed-copy inventory (`app/page.tsx`, `components/ChatLayout.tsx`, `components/ExecutionConsolePanel.tsx`) reviewed |
| DoD (specific) | 100% of identified hardcoded strings migrated to locale files; lint/CI check for new hardcoded strings passing; `docs/` note on the i18n approach (library, file layout, fallback behavior) |
| Dependencies | E15-S2, RFC-006 |

## v1 precursor / starting point

- The frontend is a Next.js 14 App Router application under `frontend/`
  with 9 routes: `/` (dashboard), `/agents`, `/config`, `/flows`, `/panels`,
  `/patches`, `/plans`, `/sessions`, and `/sessions/[sessionId]`.
- Styling is hybrid: a token-driven, Radix-based `components/ui` kit (12
  primitives — badge, breadcrumb, button, card, dialog, input, select,
  skeleton, table, tabs, toast, toaster — most with a Storybook story)
  coexists with a legacy, pre-Design-System stylesheet
  (`styles/globals.css`, 840 lines) still consumed directly by several
  pages (dashboard, config, plans, patches, agents, skills).
- There is a single shell component, `components/ChatLayout.tsx`, offering
  two layout modes (`"sidebar"` and `"focus"`) with a `sidebar-nav` /
  `sidebar-brand` structure — the closest existing analogue to the
  prototype's Execution Control Center shell, but without the 64px
  contextual header or the dismissible execution-panel slot.
- UI copy is mixed pt-BR/English with no locale infrastructure; hardcoded
  strings in both languages are present in `app/page.tsx`,
  `components/ChatLayout.tsx`, and `components/ExecutionConsolePanel.tsx`.
- Design tokens are documented in `frontend/docs/design-tokens.md`
  (`--ds-token-version: "1.0.0"`, HSL custom properties under `@layer base`
  in `styles/globals.css`, themed via `.dark`/`.light` and toggled by
  `components/ThemeToggle.tsx` / `components/ThemeProvider.tsx`), delivered
  by E10-S1.
- All of the above was delivered by E10 (Done, 2026-07-08); E15 does not
  start from zero — it evolves E10's Design System and shell toward the
  redesign prototype rather than replacing them wholesale.
- Prototype references: `layout_prototype_brainstorm/Autodev Redesing.html`
  (interactive HTML mockup), `layout_prototype_brainstorm/AutoDev - Project
  Description.pdf` (product description), and the screenshots inside
  `layout_prototype_brainstorm/Frontend redesign proposal.zip` (`shots/`
  directory).

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`)
      plus their story-specific DoD above.
- [ ] No application code under `frontend/app/` or `frontend/components/`
      references removed legacy `styles/globals.css` classes.
- [ ] i18n coverage check passes (no hardcoded, non-externalized UI strings
      in the migrated surfaces) and RFC-006's language decision is fully
      implemented (English default, pt-BR complete).
- [ ] a11y audit passes with no blocking WCAG 2.2 AA violations across the
      new shell and all migrated pages.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave §18.9 entry updated to reflect the E15 redesign scope
      (Design Language & App Shell) alongside the existing E10 entry.
