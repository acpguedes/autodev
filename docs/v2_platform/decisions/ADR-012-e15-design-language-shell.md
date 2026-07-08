# ADR-012: E15 Design Language & App Shell Implementation Decisions

- **Status:** Accepted
- **Date:** 2026-07-08
- **Authors:** AutoDev Architect maintainers
- **Related epic:** E15
- **Supersedes/Relates to:** RFC-006 (Frontend redesign — Execution Control Center)

## Context

RFC-006 (Accepted 2026-07-08) fixes the scope of the E15–E17 frontend redesign.
E15 evolves the E10 Design System (HSL token `.dark`/`.light` split,
`--ds-token-version` scheme, `components/ui` Radix/shadcn kit, Storybook,
WCAG 2.2 AA audits) toward the "Execution Control Center" prototype in
`layout_prototype_brainstorm/`. This ADR records the concrete implementation
decisions the stories E15-S1..S4 follow, resolving ambiguities between the
canonical spec (`docs/architecture/v2_platform_reference.md` §18.7.9), the
phase doc, the prototype HTML, and the current codebase.

## Decision

1. **Design tokens v2 (E15-S1).** New warm-paper light (`#faf8f4` base) /
   charcoal dark (`#100f12` base) palette with iris accent lands as an
   *additive* HSL custom-property block in `frontend/styles/globals.css`;
   no E10 token or class is removed until E15-S3. `--ds-token-version` bumps
   `"1.0.0"` → `"2.0.0"` (palette semantics change is a breaking visual
   contract).
2. **Accent color resolution.** Spec values win: `#5a4fe0` (light) /
   `#8e88ff` (dark). The prototype's `#7a72ea`/`#a7a2ff` variants become
   hover/strong states (`--accent-strong`).
3. **Fonts** load via `next/font/google` (Newsreader `--font-serif`,
   Instrument Sans `--font-sans`, JetBrains Mono `--font-mono`) — build-time
   self-hosting, zero CLS, no external `<link>`.
4. **App shell (E15-S2).** A client `AppShell` (250px sidebar rail, 64px
   contextual header, dismissible 400px execution-panel slot) mounts from
   `frontend/app/layout.tsx` and wraps every route. Panel/nav state lives in
   a `ShellProvider` React context hydrated from `sessionStorage`
   (`autodev.shell.v1`) — no global state library. Pages set header content
   through a `useShellHeader()` hook. Default theme flips dark → light with
   the shell.
5. **Navigation mismatch resolution.** The spec's "Extensions" nav item
   renders as a disabled stub until E17; existing `/agents`, `/skills`, and
   `/panels` routes stay reachable under a temporary "Legacy" nav group
   until E17 rehomes them.
6. **Migration scope correction (E15-S3).** `ChatLayout` is imported by
   **10** route files, not the 6 named in the story text; all 10 are in
   scope. E15-S2 strips `ChatLayout`'s shell responsibilities and retires
   its `focus` mode; E15-S3 deletes the component entirely and removes
   orphaned legacy rules and superseded E10 tokens (`globals.css` net line
   count must decrease below 840).
7. **i18n (E15-S4).** Minimal homegrown provider (`I18nProvider` + `useT()`
   + typed JSON dictionaries under `frontend/lib/i18n/locales/`), `en`
   default with `pt-BR` first translation. Locale persists in
   `localStorage` (`autodev.locale`) and updates
   `document.documentElement.lang`; switching re-renders client-side with no
   reload and no locale-prefixed routing. Hardcoded-copy regression guard:
   ESLint `react/jsx-no-literals` scoped to `frontend/app/**` and
   `frontend/components/**`.

## Alternatives considered

1. **next-intl / react-i18next** — full-featured but add middleware,
   locale-prefixed routing, and config surface unneeded for two locales with
   client-side switching; rejected for scope.
2. **Replacing the E10 token system wholesale in S1** — simpler end state
   but breaks the six legacy-styled pages before S3 can migrate them;
   rejected in favor of the additive-then-remove sequence.
3. **Global state library (zustand/redux) for shell state** — unnecessary
   for one context's worth of UI state; rejected.

## Consequences

- **Positive:** every route renders inside one token-driven shell;
  `ChatLayout` and ~legacy CSS are deleted; E14-S5/E16/E17 get the
  execution-panel slot and live-status surfaces they consume; UI copy is
  translatable.
- **Negative / trade-offs:** homegrown i18n must be replaced if locale
  routing/SEO becomes a requirement; temporary "Legacy" nav group persists
  until E17.
- **Contract impact:** `--ds-token-version` MAJOR bump to `2.0.0`; no
  Control Plane API change (E16 owns API enablement).

## Rollback plan

Revert the epic PR (`epic/e15-design-language-shell`); tokens are additive
until S3, so a partial rollback before S3 restores the E10 UI unchanged.
After S3, rollback requires restoring `ChatLayout.tsx` and the removed
`globals.css` rules from git history.

## References

- RFC-006 — Frontend redesign — Execution Control Center
- `docs/architecture/v2_platform_reference.md` §18.7.9
- `docs/v2_platform/phases/e15_design_language_shell.md`
- Prototype: `layout_prototype_brainstorm/Autodev Redesing.html`
