# Versioning policy

**Status:** Adopted 2026-08-21. Applies going forward from the current
`v2.0-beta` pre-release; does not retroactively rename existing tags (`v1`,
`v2.0-alpha`, `v2.0-beta`).

## Scheme: `MAJOR.MINOR.PATCH`

Git tags and published release names follow `vX.Y.Z` (optionally
`-alpha.N` / `-beta.N` / `-rc.N` before a line's first stable cut — see
below). Each component has a distinct, deliberately different meaning from
plain semver:

### `X` — generation. Breaking. Environments are not carried forward.

Bump `X` only for a change so fundamental that an environment (self-hosted
install, database, project state) running the previous generation is **not
expected to be reusable** with the new one — no in-place upgrade path is
promised. This is exactly what already happened once: `v1` (the fixed
linear pipeline) is frozen and archived; `v2` is a different platform
(plugin core, versioned extension points, Control Plane API) that a `v1`
deployment cannot be upgraded into. A future `v3` would follow the same
rule. Consequence: an operator on `vX` should expect to stand up a fresh
`vX+1` environment, not migrate one in place, unless a specific migration
tool is explicitly documented for that transition.

### `Y` — feature line. Additive. Even = stable, odd = development.

Within one `X`, `Y` increments when new features land. Minor bumps are
expected to be **rarely breaking** — an in-place upgrade within the same
`X` should normally work; any exception must be called out in that
release's notes.

**Parity convention** (mirrors the classic odd/even kernel-release scheme):

- **Even `Y`** (`2.0.x`, `2.2.x`, `2.4.x`, ...) — the **stable / production**
  line. Operators who want a settled target track only even-`Y` releases.
- **Odd `Y`** (`2.1.x`, `2.3.x`, ...) — the **development / preview** line
  where the next even-`Y`'s features are built and stabilized in the open.
  Not recommended for production; expect faster iteration and rougher
  edges than the stable line.

An odd-`Y` line is not a dead end: once its feature set is judged ready, it
is what the *next* even `Y` is cut from (e.g. `2.1.x`'s stabilized feature
set becomes `2.2.0`), rather than the odd line itself ever being labeled
stable.

**Reconciling this with the existing alpha/beta/GA wave labels.** Wave
maturity (alpha → beta → GA, tracked in `progress.md`) and the `X.Y.Z`
scheme answer different questions — "how far along is this generation's
first stable cut" vs. "which feature line and patch level" — and compose
via the pre-release suffix:

- While a given `X.Y` line has not yet reached its first stable cut, use
  `X.Y.0-alpha.N` / `X.Y.0-beta.N` / `X.Y.0-rc.N` (matching the current
  wave), e.g. today's pre-release would be `2.0.0-beta.N` under this
  scheme.
- Once that line's exit gate (`progress.md`, §18.9 of the reference doc)
  is fully met, it ships as the plain `X.Y.0` stable tag.
- Wave labels (alpha/beta/GA) therefore only ever apply to the **first**
  cut of a given `Y` (getting `2.0.0` or `2.2.0` to stable); once a stable
  `X.Y.0` exists, subsequent work on that line is patch releases (below),
  and subsequent *new* feature work moves to the next `Y`.

### `Z` — patch. Backward-compatible fixes only.

Bug fixes, no new features, no schema changes beyond what a patch release
can apply safely. Always safe to take within either the stable or the
development line it belongs to.

## Summary table

| Component | Meaning | Compatibility promise |
| --- | --- | --- |
| `X` (major) | Generation / architecture | None across `X` — treat as a fresh environment |
| `Y` (minor) | Feature line; **even = stable, odd = dev/preview** | In-place upgrade expected to work within the same `X`; exceptions must be documented per-release |
| `Z` (patch) | Bug fixes only | Always safe within its `X.Y` line |

## What this changes in practice

- New git tags for anything after the current `v2.0-beta` pre-release use
  this scheme (e.g. the GA cut of the current line is `v2.0.0`, not a bare
  `v2.0-ga` label).
- Feature work that would previously have been informally called "v2.1"
  now explicitly means: development/preview line `2.1.x`, stabilizing
  toward stable `2.2.0` — not itself a stable target.
- `docs/roadmap.md` and `docs/v2_platform/progress.md` should reference
  this document rather than re-deriving version meaning ad hoc.
