# E66 — Acceptance, Evidence and Delivery

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E65).
**Status:** Not started · **Stories:** 0/2
**Depends on:** E61, E62, E63, E64, E65 — all five
**Enables:** a single rehearsal proving the E61-E65 program actually works
together, and delivery instructions a user can follow without reading five
phase documents.
**Canonical source:** this document, plus
`docs/v2_platform/beta_acceptance_flow.md` (E35-S2), whose composed-checklist
form this epic follows.

## Context and problem

E61-E65 each prove their own slice. None of them proves the composition, and
the composition is where this program's defects actually lived: a flow was
selected wrongly *because* project state was not modelled; the panel duplicated
the chat *because* the live event path and the polled path were never joined; a
terminal could not be bound to a project *because* there were no projects.

E35-S2 established the pattern for this: a rehearsal composed from already-tested
evidence rather than a new automated suite, plus E35-S1-T3's "fact versus
recommendation" discipline — a criterion is Met only with named evidence, and
otherwise says Partial or Open rather than being quietly presumed closed.

There is a second, plainer gap. The program changes how the tool is installed,
where its data lives, how a project is recognized and how it is run. A user
following the current README after E61-E65 land would be following instructions
for a different product.

## Evidence in code and documentation

- `docs/v2_platform/beta_acceptance_flow.md` — the E35-S2 composed checklist
  this epic extends.
- `docs/v2_platform/beta_gap_analysis.md` §11 — the twelve-criterion evidence
  map and the fact-versus-recommendation rule.
- `docs/v2_platform/templates/dod_checklist.md` — the global DoD.
- `README.md`, `docs/execution/cli-install.md` — the current install and run
  instructions, which E61 and E62 invalidate.

## Objective

Prove the eight required behaviors end to end on one installation, and deliver
instructions that let someone else reproduce the proof.

## Key result

A reviewer follows one document on a clean machine, installs the tool, and
observes each of the eight behaviors — with the tracker, changelog and README
matching what they see.

## Scope

- One composed rehearsal covering the eight validations.
- Evidence recorded per validation, with Open or Partial stated where true.
- Tracker, changelog and README brought in line with the delivered behavior.

## Out of scope

- New product behavior. If the rehearsal finds a gap, it is fixed in the epic
  that owns it, not here.
- Re-running the per-story tests E61-E65 already ran. The full suite runs once
  per epic at its own PR gate, and once here for the composed change.
- Replacing `docs/v2_platform/beta_acceptance_flow.md`; this extends it.

## Stories

### E66-S1 — Composed rehearsal

Subtasks:
- `E66-S1-T1`: an executable checklist covering the eight required validations,
  in the form of `beta_acceptance_flow.md`:
  1. an implementation task does not trigger a structuring flow (E63);
  2. a task with no compatible flow executes directly (E63);
  3. the panel shows real events and does not duplicate the chat (E64);
  4. the terminal opens in the correct project and keeps its session (E65);
  5. the tool works from outside its installation directory (E61);
  6. a project is recognized from a subdirectory (E62);
  7. local configuration overrides only the fields it defines (E61);
  8. all three no-project paths work without overwriting existing data (E62).
- `E66-S1-T2`: record named evidence per validation — the test, command output
  or screenshot that supports it — and state **Open** or **Partial** where that
  is the truth, following E35-S1-T3's discipline rather than marking a row Met
  because the code exists.
- `E66-S1-T3`: run the composition on one installation, in one sitting, in the
  order a real user would hit it: install, discover or create a project, ask for
  a small change, watch the panel, open the terminal. Cross-epic defects surface
  here or nowhere.

| Criterion | Detail |
| --- | --- |
| Functional | All eight validations exercised on one installation, each with named evidence |
| Non-functional | Fact-versus-recommendation discipline: no row marked Met without evidence |
| DoR (specific) | E61-E65 complete |
| DoD (specific) | The checklist committed with its evidence column filled, including any honest Open rows |
| Dependencies | E61, E62, E63, E64, E65 |

### E66-S2 — Delivery

Subtasks:
- `E66-S2-T1`: update `docs/v2_platform/progress.md` — the six epic rows, the
  header entry, and the next action — plus `CHANGELOG.md`.
- `E66-S2-T2`: update `README.md` and `docs/execution/cli-install.md` with the
  install, run and verification instructions the program actually delivers:
  where the executable goes, where global data lives, how a project is found or
  created, and how to enable and use the terminal.
- `E66-S2-T3`: run `make check` once on the composed change, per the epic gate,
  and record the result.

| Criterion | Detail |
| --- | --- |
| Functional | A reader can install, run and verify without reading the phase documents |
| Non-functional | No aspirational behavior documented as present; flags stated with their defaults |
| DoR (specific) | E66-S1 merged |
| DoD (specific) | `make check` green; tracker, changelog and README consistent with the rehearsal's findings |
| Dependencies | E66-S1 |

## Contracts and decisions

### Architectural decisions required

None. This epic records decisions made in E61-E65; it makes none of its own.

### Security and multitenancy

- The rehearsal touches a real project and, if the terminal is exercised, a real
  shell. It must run against a scratch project, and the evidence it records must
  not contain a credential, a host name or an absolute path from a private
  machine.

### Migration strategy

None.

### Compatibility and rollback

Documentation only; rollback is reverting the documents.

## Testing and observability

Tests required:
- No new automated tests. The rehearsal composes evidence that E61-E65 already
  produced, which is exactly what E35-S2 established as the right shape for this
  kind of gate.
- `make check` once, on the composed change.

Observability:
- The rehearsal's evidence rows become the durable record of what was proven, in
  the same place `beta_gap_analysis.md` §11 keeps the wave's criteria.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A row marked Met because the code exists rather than because it was observed | The Beta gate's central failure mode, already documented in E35 | E66-S1-T2 requires named evidence per row and permits Open |
| The rehearsal finds a cross-epic defect late | Rework at the end of the program | E66-S1-T3 runs the composition in user order; the fix lands in the owning epic, which is why this epic changes no behavior |
| Documentation drifts from the delivered flags and defaults | Users enable the wrong thing, or believe the terminal is on by default | E66-S2-T2 states each flag with its default; the terminal's default-off posture is repeated where a user will read it |

## DoR / DoD

- **DoR:** E61-E65 complete; a scratch project available for the rehearsal.
- **DoD:** the eight validations exercised with named evidence and honest Open
  rows; `make check` green once; `docs/v2_platform/progress.md`, `CHANGELOG.md`,
  `README.md` and `docs/execution/cli-install.md` consistent with what was
  observed.

## Affected documents and code

Documents: a new `docs/v2_platform/e61_e66_acceptance_flow.md` (or an appended
section of `beta_acceptance_flow.md`), `docs/v2_platform/beta_gap_analysis.md`,
`docs/v2_platform/progress.md`, `CHANGELOG.md`, `README.md`,
`docs/execution/cli-install.md`.

Code: none by design.
