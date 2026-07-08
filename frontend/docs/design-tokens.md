# Design tokens

**Version:** `2.0.0` (see `--ds-token-version` in `styles/globals.css`)

> **v2 (E15-S1)** introduces the "Execution Control Center" palette,
> typefaces, and elevation as an **additive** `--ds-*` layer. The v1 (E10)
> tokens documented below remain in place until **E15-S3** migrates the
> legacy pages and removes them. See
> [Design tokens v2 (E15-S1)](#design-tokens-v2-e15-s1) for the full v2
> reference and the WCAG 2.2 AA contrast audit.

All tokens are CSS custom properties defined in `frontend/styles/globals.css`
under `@layer base`. Theme-dependent tokens (color, shadow) are declared once
under `.dark` and once under `.light`; theme-independent tokens (typography,
spacing, radius) live under `:root`. The active theme class is applied to
`<html>` by `next-themes` (see `components/ThemeProvider.tsx`), and toggled
at runtime by `components/ThemeToggle.tsx`.

## Color

HSL triplets, consumed as `hsl(var(--token))` (or with a Tailwind alpha
modifier, e.g. `bg-primary/90`). Mapped to Tailwind color utilities in
`tailwind.config.ts`.

| Token | Purpose |
| --- | --- |
| `--background` / `--foreground` | Page background / default text |
| `--card`, `--popover` | Reuse background/foreground (no separate surface color yet) |
| `--primary` / `--primary-foreground` | Primary actions, links, focus accents |
| `--secondary` / `--secondary-foreground` | Secondary surfaces and buttons |
| `--muted` / `--muted-foreground` | Low-emphasis text and backgrounds |
| `--accent` / `--accent-foreground` | Hover/active highlight |
| `--destructive` / `--destructive-foreground` | Errors, dangerous actions |
| `--success` / `--success-foreground` | Success states |
| `--border`, `--input`, `--ring` | Borders, form field borders, focus rings |

Legacy tokens (`--bg`, `--panel`, `--panel-alt`, `--ui-border`, `--text`,
`--ui-muted`, `--ui-accent`, `--accent-strong`, `--danger`) back the
pre-Tailwind page styling and are also themed per `.dark`/`.light`.

## Typography

`--font-sans`, `--font-mono`, `--text-{xs,sm,base,lg,xl,2xl,3xl}`,
`--leading-{tight,normal,relaxed}`, `--font-weight-{normal,medium,semibold,bold}`.

## Spacing

4px base scale: `--space-{1,2,3,4,5,6,8,10,12}`.

## Radius

`--radius` (base), with `lg`/`md`/`sm` derived in `tailwind.config.ts`.

## Shadow

`--shadow-sm`, `--shadow-md`, `--shadow-lg` — re-declared per theme so
elevation reads correctly against both backgrounds.

## Usage

Prefer the Tailwind utility classes (`bg-primary`, `text-muted-foreground`,
`shadow-md`, `rounded-lg`, …) over raw `var(--token)` references in new
components; base components in `components/ui/` follow this convention.

## Design tokens v2 (E15-S1)

The v2 layer implements the "Execution Control Center" language from
`layout_prototype_brainstorm/Autodev Redesing.html`, pinned by
[ADR-012](../../docs/v2_platform/decisions/ADR-012-e15-design-language-shell.md).
The color/radius/shadow layer is **additive**: it lives entirely under the
`--ds-*` prefix and the `ds` Tailwind namespace, so no v1 color, radius, or
shadow token or class changes until E15-S3. Colors are HSL triplets
(`hsl(var(--ds-token))`), enabling alpha modifiers for the prototype's
tints — e.g. `bg-ds-success/12` or `hsl(var(--ds-accent) / 0.16)`.

**Fonts are the one intentional exception** (ADR-012 §3): the v2 typefaces
reuse the existing `--font-sans` / `--font-mono` variable names (plus new
`--font-serif`) rather than a `--ds-*` alias, so attaching them to `<body>`
in `app/layout.tsx` shifts the app-wide default sans/mono from Inter / SF
Mono to Instrument Sans / JetBrains Mono immediately in S1. The v1 `:root`
declarations remain as the no-JS fallback (see [Migration
notes](#migration-notes)); no consumer markup changes.

Tailwind utilities: `bg-ds-bg`, `text-ds-fg`, `text-ds-fg-2`,
`border-ds-line`, `bg-ds-accent text-ds-accent-fg`, `text-ds-success`,
`rounded-ds-lg`, `shadow-ds-md`, `font-serif`, …

### Light palette (`:root, .light`)

| Token | Hex | HSL | Role |
| --- | --- | --- | --- |
| `--ds-bg` | `#faf8f4` | `40 37% 97%` | App background (warm paper) |
| `--ds-bg-2` | `#ffffff` | `0 0% 100%` | Raised surface / cards, sidebar |
| `--ds-bg-3` | `#f3f0ea` | `40 27% 94%` | Inset / secondary surface |
| `--ds-bg-4` | `#ece8df` | `42 25% 90%` | Deep inset / chips |
| `--ds-line` | `#e7e2d8` | `40 24% 88%` | Divider / hairline border |
| `--ds-line-strong` | `#d6d0c3` | `41 19% 80%` | Emphasized border / scrollbar |
| `--ds-fg` | `#1b1a17` | `45 8% 10%` | Primary text |
| `--ds-fg-2` | `#57544c` | `44 7% 32%` | Secondary text |
| `--ds-fg-3` | `#8f8b80` | `44 6% 53%` | Tertiary text (large / UI only) |
| `--ds-accent` | `#5a4fe0` | `245 70% 59%` | Accent / links (ADR-012 spec) |
| `--ds-accent-strong` | `#7a72ea` | `244 74% 68%` | Accent hover / active |
| `--ds-accent-fg` | `#ffffff` | `0 0% 100%` | Text on accent |
| `--ds-success` | `#16834a` | `149 71% 30%` | Success text/icon (nudged) |
| `--ds-warn` | `#9f640f` | `35 83% 34%` | Warning text/icon (nudged) |
| `--ds-danger` | `#c74639` | `5 56% 50%` | Danger text/icon (nudged) |
| `--ds-add-bg` | `#e3f4e8` | `138 44% 92%` | Diff add background |
| `--ds-add-fg` | `#136c3c` | `148 70% 25%` | Diff add text |
| `--ds-add-gut` | `#8fce9f` | `135 39% 68%` | Diff add gutter |
| `--ds-del-bg` | `#fbe6e3` | `8 75% 94%` | Diff delete background |
| `--ds-del-fg` | `#a83a2f` | `5 56% 42%` | Diff delete text |
| `--ds-del-gut` | `#e3a79c` | `9 56% 75%` | Diff delete gutter |

### Dark palette (`.dark`)

| Token | Hex | HSL | Role |
| --- | --- | --- | --- |
| `--ds-bg` | `#100f12` | `260 9% 6%` | App background (charcoal) |
| `--ds-bg-2` | `#171519` | `270 9% 9%` | Raised surface / cards, sidebar |
| `--ds-bg-3` | `#201e24` | `260 9% 13%` | Inset / secondary surface |
| `--ds-bg-4` | `#28262e` | `255 10% 16%` | Deep inset / chips |
| `--ds-line` | `#2a2830` | `255 9% 17%` | Divider / hairline border |
| `--ds-line-strong` | `#3b3944` | `251 9% 25%` | Emphasized border / scrollbar |
| `--ds-fg` | `#f4f2ee` | `40 21% 95%` | Primary text |
| `--ds-fg-2` | `#b3afa6` | `42 8% 68%` | Secondary text |
| `--ds-fg-3` | `#7c7970` | `45 5% 46%` | Tertiary text (large / UI only) |
| `--ds-accent` | `#8e88ff` | `243 100% 77%` | Accent / links (ADR-012 spec) |
| `--ds-accent-strong` | `#a7a2ff` | `243 100% 82%` | Accent hover / active |
| `--ds-accent-fg` | `#100f12` | `260 9% 6%` | Text on accent |
| `--ds-success` | `#5fce8c` | `144 53% 59%` | Success text/icon |
| `--ds-warn` | `#e0a94e` | `37 70% 59%` | Warning text/icon |
| `--ds-danger` | `#f0796d` | `5 81% 68%` | Danger text/icon |
| `--ds-add-bg` | `#122419` | `143 33% 11%` | Diff add background |
| `--ds-add-fg` | `#6bd393` | `143 54% 62%` | Diff add text |
| `--ds-add-gut` | `#2f6444` | `144 36% 29%` | Diff add gutter |
| `--ds-del-bg` | `#2a1512` | `8 40% 12%` | Diff delete background |
| `--ds-del-fg` | `#f0837a` | `5 80% 71%` | Diff delete text |
| `--ds-del-gut` | `#6e332b` | `7 44% 30%` | Diff delete gutter |

### Typography

Loaded via `next/font/google` in `app/layout.tsx` (self-hosted, zero CLS),
exposed as CSS variables and Tailwind `font-*` families:

| Variable / class | Family | Role |
| --- | --- | --- |
| `--font-serif` / `font-serif` | Newsreader | Display / shell headings |
| `--font-sans` / `font-sans` | Instrument Sans | Body and UI copy |
| `--font-mono` / `font-mono` | JetBrains Mono | Code, diffs, metrics |

Serif display scale (`:root`): `--ds-display-lg` (36px), `--ds-display-md`
(28px), `--ds-display-sm` (22px), paired with `--ds-display-leading` (1.15).

### Radius & elevation

Radius scale: `--ds-radius-sm` (6px), `--ds-radius-md` (10px),
`--ds-radius-lg` (12px), `--ds-radius-xl` (16px), `--ds-radius-full`
(pill) — Tailwind `rounded-ds-{sm,md,lg,xl,full}`.

Shadow scale (re-declared per theme): `--ds-shadow-sm`, `--ds-shadow-md`,
`--ds-shadow-lg` — Tailwind `shadow-ds-{sm,md,lg}`.

### WCAG 2.2 AA contrast audit

Contrast ratios for every foreground/background pair (target ≥ 4.5:1 for
body text, ≥ 3:1 for large text and UI). Ratios are computed from the
**shipped integer HSL triplets** (i.e. the RGB the browser renders, matching
axe-core), not the source hex, so the thin-margin status pairs are honest.
Verified by `lib/__tests__/design-tokens.test.ts` presence checks plus the
Storybook axe-core run over the `UI/Card → Design tokens v2` story.

| Pair | Light | Dark | Min |
| --- | --- | --- | --- |
| `fg` on `bg` | 16.26 | 17.38 | 4.5 |
| `fg` on `bg-2` | 17.23 | 16.38 | 4.5 |
| `fg` on `bg-3` | 15.30 | 14.90 | 4.5 |
| `fg` on `bg-4` | 14.09 | 13.65 | 4.5 |
| `fg-2` on `bg` | 7.13 | 8.90 | 4.5 |
| `fg-2` on `bg-3` | 6.71 | 7.63 | 4.5 |
| `fg-3` on `bg` (large/UI) | 3.22 | 4.36 | 3.0 |
| `accent` on `bg` | 5.56 | 6.66 | 4.5 |
| `accent` on `bg-2` | 5.89 | 6.28 | 4.5 |
| `accent-fg` on `accent` | 5.89 | 6.66 | 4.5 |
| `success` on `bg` | 4.52 | 9.79 | 4.5 |
| `warn` on `bg` | 4.64 | 9.05 | 4.5 |
| `danger` on `bg` | 4.59 | 6.85 | 4.5 |
| `add-fg` on `add-bg` | 5.66 | 8.60 | 4.5 |
| `del-fg` on `del-bg` | 5.40 | 6.76 | 4.5 |

**Adjustments from the prototype.** To clear 4.5:1 for status *text* on the
light `--ds-bg`, three light colors had their lightness nudged 1–2 points
(hue/saturation unchanged): `--ds-success` `#178a4e`→`#16834a`,
`--ds-warn` `#a86a10`→`#9f640f`, `--ds-danger` `#c8483b`→`#c74639`. All
other colors are the prototype values verbatim.

**`--ds-fg-3` and dividers.** `--ds-fg-3` is a tertiary/placeholder tone and
clears AA only at the 3:1 large-text/UI threshold; do not use it for body
copy. `--ds-line` / `--ds-line-strong` are decorative separators (≈1.5:1 on
`--ds-bg`) and are exempt from 1.4.11 — interactive controls are identified
by fill contrast and the accent focus ring, never by a hairline alone.

### Migration notes

- **Additive until E15-S3.** All v1 tokens (`--background`, `--foreground`,
  `--bg`, `--panel`, `--radius`, `--shadow-*`, …) and their Tailwind
  mappings remain. v2 uses distinct `--ds-*` / `ds` names to avoid any
  collision; E15-S3 deletes the superseded v1 set.
- **Fonts.** `--font-sans` / `--font-mono` are now sourced from
  `next/font/google` on `<body>` (Instrument Sans / JetBrains Mono),
  shadowing the v1 `:root` Inter / SF Mono fallbacks, which stay as the
  no-JS fallback. `--font-serif` (Newsreader) is net-new.
- **Elevation naming.** v2 shadows are `--ds-shadow-*` rather than reusing
  v1 `--shadow-*`, so existing components keep their elevation until they
  opt in.

## Changelog

- **2.0.0** — Design tokens v2 (E15-S1): additive `--ds-*` "Execution
  Control Center" palette (warm-paper light / charcoal dark, iris accent),
  Newsreader/Instrument Sans/JetBrains Mono typefaces via `next/font`,
  serif display scale, radius/elevation scales, and `ds` Tailwind namespace.
  All fg/bg pairs verified WCAG 2.2 AA; three light status colors nudged
  1–2 lightness points. v1 tokens retained until E15-S3.
- **1.0.0** — Initial versioned token set (E10-S1): added typography,
  spacing, and shadow tokens; themed the legacy shell variables for
  light/dark parity; added `input`/`ring`/`success`/`card`/`popover` to the
  Tailwind color mapping.
