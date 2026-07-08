# Design tokens

**Version:** `1.0.0` (see `--ds-token-version` in `styles/globals.css`)

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

## Changelog

- **1.0.0** — Initial versioned token set (E10-S1): added typography,
  spacing, and shadow tokens; themed the legacy shell variables for
  light/dark parity; added `input`/`ring`/`success`/`card`/`popover` to the
  Tailwind color mapping.
