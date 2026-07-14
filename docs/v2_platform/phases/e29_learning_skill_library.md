# E29 — Durable Learning & Skill Library

**Wave:** v2.2 — Concept Integration (after E6/E7; curation loop consumes
E22 gate verdicts when present).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E6 (skills registry), E7 (embeddings, retrieval, context
providers), E8 (State Store, tenant scoping), E22 (gate verdicts as the
promotion signal)
**Enables:** E25 (Extension Studio publishes library entries), E13
(marketplace sharing path), better cold-start performance for every agent
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.5,
§18.7.21; RFC-008

## Objective

Give the platform **memory that compounds**: a durable, tenant-scoped
skill/playbook library where verified artifacts (procedures, prompts, code
snippets, task recipes) are embedding-indexed and retrieved on demand; an
incremental curation loop that turns run experience into playbook deltas
(never wholesale rewrites, no fine-tuning); a progressive-disclosure skill
pack format interoperable with the external ecosystem; and machine-generated
repo knowledge that keeps a navigable, current picture of each codebase.

## Key result

An agent starting a task retrieves the top-k relevant playbooks/skills
(measured retrieval, not prompt stuffing); after verified runs, a curator
pass proposes bounded playbook deltas that a reviewer (human or policy)
accepts into new immutable versions; a repeated task class shows measured
improvement (fewer iterations/tokens to `success`) attributable to library
hits — all without touching model weights.

## Prior art (condensed)

Voyager (verified code skills, embedding-indexed by NL description, top-k
retrieved and composed), ACE (generator/reflector/curator producing
incremental context deltas; avoids brevity bias and context collapse),
Reflexion/ExpeL (episodic reflection, cross-trajectory insights), Devin
(playbooks, curated + auto-scanned Knowledge, auto-generated repo wiki),
Windsurf Memories (corrections auto-stored and auto-referenced), Claude Code
Skills (folder packs, progressive disclosure via frontmatter-first loading).
Sources and evidence grades in RFC-008.

## Stories

### E29-S1 — Skill/playbook library (verified, embedding-indexed)

Subtasks:
- `E29-S1-T1`: library entry contract — kinds `playbook` (procedural
  guidance bound to a task class), `snippet` (verified code artifact), and
  `insight` (reusable lesson); each entry: NL description, body,
  provenance (source runs/patches/gates), verification status, SemVer,
  immutable published versions (E20-S2 registry pattern).
- `E29-S1-T2`: storage + indexing — State Store rows + pgvector embeddings
  of descriptions/bodies (E7-S2 provider reused); MinIO for large bodies;
  tenant-scoped with RLS (E8-S1).
- `E29-S1-T3`: `/v2/knowledge` (register/list/search/detail, §14.1) +
  `knowledge.*` events; retrieval API returns top-k with scores
  (E7-S3 hybrid ranking reused).

| Criterion | Detail |
| --- | --- |
| Functional | Entries are retrievable by semantic + lexical search with scores; provenance links resolve to real runs/patches; published versions immutable |
| Non-functional | Retrieval P95 within the E7-S3 budget; library size does not degrade agent-start latency (top-k, never full scan) |
| DoR (specific) | RFC-008 accepted; epic ADR (knowledge/skill-library schema & curation loop) filed |
| DoD (specific) | CRUD/search/provenance contract tests; `docs/knowledge/library.md` |
| Dependencies | E6, E7-S2/S3, E8, E20-S2 (registry pattern) |

### E29-S2 — Incremental curation loop (ACE pattern)

Subtasks:
- `E29-S2-T1`: reflector — after a harness run finishes (any typed result
  state), an optional reflection pass extracts candidate lessons: what
  worked, what failed, error patterns (E26-S4 keep-errors feeds this).
- `E29-S2-T2`: curator — turns candidate lessons into **bounded deltas**
  against existing entries (add/amend/deprecate one item at a time), never
  wholesale rewrites; deltas carry evidence links (gate verdicts, cost
  comparisons).
- `E29-S2-T3`: promotion policy — deltas enter `proposed` state; promotion
  to a published version requires the configured signal (human review by
  default; policy-auto for `insight` kind with strong evidence); rejected
  deltas retained for audit; decay policy deprecates entries unused/failing
  over a window.

| Criterion | Detail |
| --- | --- |
| Functional | A verified run produces at most bounded deltas (size-capped); promotion requires the configured signal and is evented; a stale entry decays to `deprecated` per policy, never silently deleted |
| Non-functional | Curation cost metered against a dedicated budget; loop cannot self-amplify (curator output is not curator input within one cycle) |
| DoR (specific) | E29-S1 available; E22 verdict access reviewed |
| DoD (specific) | Delta-bounding, promotion-gate, and decay tests; `docs/knowledge/curation.md` |
| Dependencies | E29-S1, E22, E23 (run results), E26-S4 |

### E29-S3 — Progressive-disclosure skill packs & interop

Subtasks:
- `E29-S3-T1`: pack format — a skill pack is a folder artifact (manifest +
  instruction body + optional scripts/resources) whose **descriptor**
  (name, one-line description, trigger hints) is loadable separately from
  the body; the runtime injects descriptors only, loading bodies on demand.
- `E29-S3-T2`: interop — import external `SKILL.md`-style packs into the
  library (mapped to E29-S1 entries) and export library entries as packs;
  round-trip preserves content; imported packs enter `unverified` status
  until they pass the E6 contract test.
- `E29-S3-T3`: runtime wiring — descriptor injection composes with E26
  (descriptors live in the stable prefix region; bodies arrive as
  retrieval results, not prefix mutations).

| Criterion | Detail |
| --- | --- |
| Functional | A task that never triggers a pack never loads its body (measured); import→export round-trips; unverified imports cannot auto-execute scripts |
| Non-functional | Descriptor overhead per pack bounded and documented; packs tenant-scoped |
| DoR (specific) | E29-S1 available; E6 skill contract reviewed (pack is an additive packaging, not a new kind) |
| DoD (specific) | Lazy-load, round-trip, and quarantine tests; `docs/knowledge/packs.md` |
| Dependencies | E29-S1, E6, E26-S1 |

### E29-S4 — Machine-generated repo knowledge

Subtasks:
- `E29-S4-T1`: knowledge builder — a scheduled/triggered job that renders
  repo intelligence (E7 index: modules, symbols, dependencies; plus the
  knowledge-graph artifacts where present, e.g. the in-repo graphify
  output) into navigable knowledge entries: architecture overview, module
  summaries, entry-point maps, each linked to source.
- `E29-S4-T2`: freshness — builder runs incrementally on patch-apply
  events; entries carry the commit they describe; stale entries flagged,
  not served silently.
- `E29-S4-T3`: consumption — exposed as a context provider (E7-S4) so
  agents/harnesses pull repo knowledge through the same retrieval path as
  playbooks ("Spine"-compatible bundles for spec-scoped work).

| Criterion | Detail |
| --- | --- |
| Functional | After indexing, an agent can retrieve an accurate module summary with source links; a patch changing a module flags/refreshes its entries; knowledge is served only through the retrieval path (no prompt-stuffed dumps) |
| Non-functional | Incremental rebuild cost proportional to the diff, not repo size; generation deterministic for a frozen index (ADR-005) |
| DoR (specific) | E29-S1 available; E7-S1/S4 index + provider contracts reviewed |
| DoD (specific) | Accuracy fixture (seeded repo), staleness, and provider tests; `docs/knowledge/repo-knowledge.md` |
| Dependencies | E29-S1, E7, E16-S3 (patch events) |

## v1/v2 precursor / starting point

- E6 registers skills and E7 retrieves code context, but nothing today
  persists *experience*: no playbooks, no lesson curation, no repo wiki;
  every run starts cold. Agent memory (§6.5) stores per-agent state, not a
  shared, versioned, verified library — E29-S1 is the missing shared tier.
- The E20-S2 Spec Registry establishes the tenant-scoped immutable-version
  registry pattern E29-S1 copies; the E22 traceability graph provides the
  provenance edges entries link to.
- graphify's knowledge graph (repo root `graphify-out/`) demonstrates the
  repo-knowledge value locally; E29-S4 productizes the pattern behind the
  platform's own index and context-provider seams.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for library entries, curation deltas, packs, and
      repo knowledge.
- [ ] Epic ADR (knowledge/skill-library schema & curation loop) filed before
      E29-S1 implementation starts.
- [ ] `knowledge.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
