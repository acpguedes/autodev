# E31 — Library Spec Registry

**Wave:** v2.2 — Concept Integration (after E20; publish path feeds E13).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E20 (spec contracts, registry pattern), E7 (retrieval,
context providers), E14 (sandbox for verification runs), E13 (marketplace
publish path, for S4)
**Enables:** anti-hallucination context for every codegen run, E13
marketplace content, E29 knowledge entries for dependencies
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.7,
§18.7.23; RFC-008

## Objective

Resolve RFC-007's deferred open question with a **registry of verified specs
for external dependencies** ("spec-as-lockfile"): a versioned, tenant-scoped
store of per-`library@version` contracts (public API surface, behavioral
notes, verified usage examples) that is injected at retrieval time so agents
stop hallucinating APIs and mixing versions — acquired by a verification
pipeline that tests every claim against the real library in the sandbox, and
shareable through the marketplace with provenance.

## Key result

A codegen task against a repo whose lockfile pins `somelib@2.3` retrieves
the verified spec for exactly that version (not 1.x, not latest); a seeded
API-hallucination fixture shows the drop in invented-API errors with the
registry on; every spec claim marked `verified` traces to a sandbox run that
exercised it; and a tenant can import/publish library specs with signatures
and provenance intact.

## Prior art (condensed)

Tessl Spec Registry (10k+ pre-built specs for OSS libraries against API
hallucination and version mixups; spec-as-source framework itself remains
the rejected posture per RFC-007), dependency-hallucination failure reports,
Devin Knowledge (curated per-dependency notes), RFC-007's spec registry
pattern (immutable published versions, deltas) which this epic instantiates
for third-party code. Sources in RFC-008.

## Stories

### E31-S1 — Dependency-spec contract & registry

Subtasks:
- `E31-S1-T1`: `library-spec.yaml` contract — identity
  (`ecosystem:package@version-range`), public API surface (modules,
  signatures, types), behavioral clauses (EARS grammar reused from E20
  where applicable), verified usage examples, deprecation/migration notes;
  standard manifest shape (schemaVersion, SemVer, JSON schema, SDK export,
  contract test).
- `E31-S1-T2`: registry persistence — tenant-scoped, immutable published
  versions, delta model for updates (E20-S2/S3 pattern reused; one
  registry implementation, two artifact kinds).
- `E31-S1-T3`: `/v2/library-specs` (register/list/resolve, §14.1) —
  `resolve` maps a lockfile entry to the best matching spec version;
  `library_spec.*` events appended.

| Criterion | Detail |
| --- | --- |
| Functional | A spec registers only if schema-valid; `resolve("pypi:somelib==2.3.1")` returns the matching spec or a typed miss; published versions immutable |
| Non-functional | Version-range matching deterministic (ADR-005); registry queries within E20-S2 latency budgets |
| DoR (specific) | RFC-008 accepted; epic ADR (library-spec format & acquisition pipeline) filed |
| DoD (specific) | Contract + resolution tests incl. range edge cases; `docs/library-specs/contract.md` |
| Dependencies | E20-S1/S2, E1 |

### E31-S2 — Spec acquisition & verification pipeline

Subtasks:
- `E31-S2-T1`: acquisition flow — generate a candidate spec for a
  `library@version` from its published artifacts (typed stubs, docs,
  signatures via the E7 indexer where source is available); runs as an
  ordinary flow (E3) so it is budgeted, checkpointed, and traced.
- `E31-S2-T2`: claim verification — every API-surface claim and usage
  example is executed against the real installed library in the sandbox
  (E14); claims that pass are `verified`, others `unverified` — status is
  per-claim, not per-spec; a spec with failing claims can publish only with
  the failures marked.
- `E31-S2-T3`: refresh triggers — new library versions detected from
  lockfile changes queue acquisition; specs carry the toolchain fingerprint
  they were verified against.

| Criterion | Detail |
| --- | --- |
| Functional | An acquired spec's verified claims each trace to a sandbox execution; a deliberately wrong claim ends `unverified`; a lockfile bump queues acquisition for the new version |
| Non-functional | Acquisition budgeted per library (fail-closed); pipeline deterministic for frozen inputs where generation is not LLM-bound, with LLM steps behind the ADR-005 boundary |
| DoR (specific) | E31-S1 available; E14 sandbox contracts reviewed |
| DoD (specific) | Verification-trace, wrong-claim, and trigger tests; `docs/library-specs/acquisition.md` |
| Dependencies | E31-S1, E3, E14, E7 |

### E31-S3 — Retrieval integration (anti-hallucination context)

Subtasks:
- `E31-S3-T1`: lockfile coupling — the repo indexer (E7) parses dependency
  manifests/lockfiles; the resolved dependency set is part of repo context
  metadata.
- `E31-S3-T2`: context provider — a `context_provider` (E7-S4 seam) that,
  for a task touching dependency X, injects the relevant slice of X's
  verified spec (top-k API entries by task relevance, never the full spec)
  through the standard retrieval path; composes with "Spine" bundles
  (E20-S5) for spec-scoped work.
- `E31-S3-T3`: effectiveness measurement — a seeded hallucination fixture
  (tasks against libraries with commonly-invented APIs) tracked as an eval
  (E5/E12) comparing registry-on vs registry-off.

| Criterion | Detail |
| --- | --- |
| Functional | A task touching `somelib` receives verified-spec context for the pinned version only; injection is top-k scoped (measured tokens); the hallucination eval reports registry-on vs off deltas |
| Non-functional | Provider adds bounded latency within E7-S3 budgets; unverified claims clearly marked in injected context |
| DoR (specific) | E31-S1 available; E7-S4 provider contract reviewed |
| DoD (specific) | Resolution-scoping, marking, and eval-fixture tests; `docs/library-specs/retrieval.md` |
| Dependencies | E31-S1, E7-S4, E20-S5, E5/E12 (eval) |

### E31-S4 — Sharing & marketplace publish path

Subtasks:
- `E31-S4-T1`: import/export — library specs exportable as signed
  artifacts and importable across tenants/installs; imported specs land
  `unverified` until re-verified locally (E31-S2 pipeline) or trusted via
  signature policy.
- `E31-S4-T2`: publish path — publishing to the marketplace reuses the E13
  verified-publish flow (signature + SBOM-style provenance: who generated,
  what toolchain, which claims verified); private by default, licensing
  metadata mandatory at publish (RFC-008 guidance 3).
- `E31-S4-T3`: community seed — a curated seed set for the most common
  ecosystems ships as importable content (not hardcoded), so self-hosted
  installs start useful.

| Criterion | Detail |
| --- | --- |
| Functional | Export→import round-trips with signatures verified; an imported unverified spec cannot serve `verified`-marked context until re-verified or trusted; publish requires licensing metadata |
| Non-functional | Trust decisions auditable; seed import idempotent |
| DoR (specific) | E31-S2 available; E13 publish flow scoped (S4 may trail E13 GA) |
| DoD (specific) | Round-trip, trust-policy, and publish-gate tests; `docs/library-specs/sharing.md` |
| Dependencies | E31-S1/S2, E13, E11 (audit) |

## v1/v2 precursor / starting point

- RFC-007 explicitly deferred this ("library-spec registry: later epic or
  out of scope") — E31 answers *in scope, as v2.2*: dependency-API
  hallucination is a measured top failure mode of codegen, and the platform
  already owns every piece needed (registry pattern from E20, sandbox from
  E14, retrieval seams from E7, publish path from E13).
- The E20 Spec Registry stores *our* intent; E31 stores *the world's*
  contracts. Same persistence pattern, different artifact kind and
  acquisition path — one implementation, no new subsystem.
- E29-S4's repo knowledge covers first-party code; E31 covers third-party
  dependencies; both serve through the same E7 context-provider seam.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for the spec contract, acquisition pipeline,
      retrieval provider, and sharing path.
- [ ] Epic ADR (library-spec format & acquisition pipeline) filed before
      E31-S1 implementation starts.
- [ ] `library_spec.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
