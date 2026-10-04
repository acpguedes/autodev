# ADR-028: Layered Configuration Semantics (Absence vs. Falsiness)

- **Status:** Accepted
- **Date:** 2026-09-05
- **Authors:** AutoDev platform team
- **Related epic:** E61
- **Supersedes/Relates to:** ADR-015 (Global Installation Strategy), extended
  by this ADR's Consequences rather than superseded

## Context

E61-S1 introduced a single global home (`AUTODEV_HOME`/`~/.autodev`) for
configuration and data that belongs to the tool rather than to one project.
E61-S2 composes the active `RuntimeConfig` from three layers, in increasing
priority: internal defaults, the global configuration file, and the
per-project configuration file (`autodev.config.json`). This composition is a
MINOR change to a public configuration contract (reference §19.1/§19.3) and
needs one explicit rule, since every current and future field inherits it.

The pre-E61 implementation (`RuntimeConfigService._normalize`) collapsed any
falsy value — `""` today, and by the same shape a future `False`/`0` — to
that field's default via `value.strip() or <default>`. That conflated two
different conditions: "the user did not set this field" and "the user set
this field to an empty/falsy value". Only the first should ever defer to a
lower layer.

## Decision

**Absence is key-absence, never falsiness.** A configuration layer
contributes a field only when that field's key is present in its JSON
document. A present key's value — including `""`, and by the same rule a
future `false` or `0` — always wins over any lower layer, and is never
replaced by a default merely because it is falsy.

Mechanically: each layer is read as a plain, sparse JSON object (not a fully
materialized `RuntimeConfig`). Layers are deep-merged per field, lowest
priority first (internal defaults → global → project), via `_deep_merge`
(`backend/config/runtime.py`) — a dict value is merged recursively; any other
value present in the higher-priority layer simply replaces the lower one,
regardless of what that value is. Only after the full document is composed
is it validated into a `RuntimeConfig`.

The corollary for writes: `RuntimeConfigService.save()` persists only the
fields that differ from what the defaults+global layers would already
produce (`_diff_document`) — an inherited value is never duplicated into the
project file merely because the full materialized config carries it. This is
the mechanism, not a special case, behind "a global credential is never
copied into a project file by inheritance": it falls out of the same
diff for every field, api_key included.

## Consequences

- Every field defined on `RuntimeConfig` today (`llm.*`, `repository.*`) and
  every field added in the future inherits this rule automatically — there
  is no per-field opt-in.
- An existing `autodev.config.json` that relied on the old collapse (e.g. an
  empty `repository_label` silently becoming `"Current workspace"`) now
  keeps the empty value it was written with. This is called out in
  `CHANGELOG.md` and `docs/execution/paths-and-config.md`: the old behavior
  was the defect being fixed, not a contract being broken.
- `autodev.config.json` files written by `save()` after this change may be
  sparser than before (a field equal to its inherited value is omitted) —
  this is expected and not itself observable through `RuntimeConfigService`,
  only by reading the raw file.
- ADR-015 (Global Installation Strategy) is extended, not superseded: its
  Consequences section now also covers where the tool's own configuration
  state lives (`AUTODEV_HOME`), which this ADR's composition rule governs.
