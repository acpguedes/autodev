# Contributing to AutoDev Architect

This guide applies to every contributor — human or coding agent. It covers the
development environment, the branching model, coding standards, the testing
policy, and how changes land in `main`. The rules here are binding for all v2
platform work (`E<n>-S<m>` stories tracked under `docs/v2_platform/`).

Related documents:

- `docs/v2_platform/agent_guide.md` — story workflow gates (G1–G5), DoR/DoD,
  ADR/RFC triggers, naming and versioning conventions.
- `docs/v2_platform/progress.md` — where the v2 rewrite stands (waves, epics,
  stories).
- `docs/testing.md` — test tooling details.
- `AGENTS.md` / `CLAUDE.md` — agent-specific operating guidance.

## 1. Development environment

Backend work should prefer the containerized runtime introduced by E0:

```bash
make container-build          # build the backend dev/test image
make container-test           # run backend tests inside the container
make container-check          # lint + typecheck + tests inside the container
```

For host-local work, always use the project virtualenv:

```bash
python -m venv .venv          # first time only
source .venv/bin/activate
make install-backend
```

Never run `python`/`pip`/`pytest` outside the venv or the container.

## 2. Branching and merge workflow

`main` is the stable branch. Work is organized by **epic** and **story**
following the `E<n>`/`E<n>-S<m>` roadmap in `docs/v2_platform/`.

### Rules

1. **One branch per epic.** When an epic starts, create its branch from the
   latest `main` and push it to the remote:

   ```bash
   git checkout main && git pull
   git checkout -b epic/e3-orchestration-engine
   git push -u origin epic/e3-orchestration-engine
   ```

2. **One branch per story.** Each story gets its own branch, created from the
   epic branch (never from `main`):

   ```bash
   git checkout epic/e3-orchestration-engine
   git checkout -b story/e3-s1-flow-spec
   ```

3. **Story completion.** When a story is Done (its DoD is met), merge the story
   branch into the epic branch, push the epic branch to the remote, and delete
   the story branch (local and remote, if pushed):

   ```bash
   git checkout epic/e3-orchestration-engine
   git merge --no-ff story/e3-s1-flow-spec
   git push origin epic/e3-orchestration-engine
   git branch -d story/e3-s1-flow-spec
   git push origin --delete story/e3-s1-flow-spec   # only if it was pushed
   ```

4. **Epic completion.** When the epic's last story is Done, open a **pull
   request** from the epic branch to `main`. The full test suite must be green
   (see §4). Merge happens via the PR — never merge an epic branch into `main`
   locally. Delete the epic branch after the PR merges.

5. **Naming.** Use `epic/e<N>-<slug>` and `story/e<N>-s<M>-<slug>`, kebab-case.
   (Branches created before this convention used `feat/…`; do not rename them —
   the convention applies from E3 onward.)

6. Work that is not part of an epic (hotfixes, docs, tooling) uses a short-lived
   branch from `main` (`fix/…`, `docs/…`, `chore/…`) and merges back via PR.

### Diagram

```
main ──────────────────────────────────────────────► (PR merge only)
  └── epic/e3-orchestration-engine ────────────────► PR → main
        ├── story/e3-s1-flow-spec      → merge into epic, delete
        ├── story/e3-s2-checkpointing  → merge into epic, delete
        └── story/e3-s3-…              → merge into epic, delete
```

## 3. Coding standards

1. **Docstrings are mandatory.** Every package (`__init__.py`), module, class,
   method, and function must have a docstring with a description and, where
   applicable, its arguments, return value, and raised errors. Use Google
   style:

   ```python
   def resolve(self, name: str, constraint: str) -> AgentManifest:
       """Resolve the best agent manifest for a SemVer constraint.

       Args:
           name: Fully qualified agent id (``namespace/name``).
           constraint: SemVer range, e.g. ``">=2.0 <3.0"``.

       Returns:
           The highest registered manifest version satisfying ``constraint``.

       Raises:
           AgentNotFoundError: If no registered version satisfies the range.
       """
   ```

2. **Type hints are mandatory.** All classes (attributes where meaningful),
   methods, and functions must have complete type annotations on parameters and
   return types. `mypy` must pass (`make typecheck`).

3. **English only.** All code annotations, docstrings, comments, identifiers,
   commit messages, and documentation are written in English. (The only
   exception is `docs/architecture/v2_platform_reference.md`, whose declared
   scope is pt-BR.)

4. Follow the repository conventions already enforced by tooling: `black`,
   `ruff`, `mypy` (`make lint typecheck`), files under 500 lines, input
   validation at system boundaries, no secrets in code or diffs.

## 4. Testing policy

The goal is fast story iteration with a strict gate at `main`.

1. **Avoid unnecessary tests.** Do not add tests that duplicate existing
   coverage or test framework/library behavior. Every new test must protect a
   behavior of the story being delivered.

2. **Story scope: run only the story's tests.** While working on a story, run
   the test modules that cover the code you changed, e.g.:

   ```bash
   pytest backend/tests/agents -q                 # area-scoped
   pytest backend/tests -k "registry" -q          # selection-scoped
   ```

   Run additional test areas only when it makes sense — e.g. when the story
   touches a shared contract (manifest schemas, persistence, the plugin host)
   that other modules depend on.

3. **Epic → `main`: run everything.** Before opening (and before merging) the
   epic PR to `main`, the **full** suite must pass — backend and frontend —
   plus lint and typecheck:

   ```bash
   make check            # host: lint + typecheck + all tests + build
   make container-check  # same gate inside the backend container
   ```

4. **Parallel execution.** The backend suite may be run in parallel with
   `pytest-xdist` (`pip install pytest-xdist`, then `pytest -n auto`) to speed
   up the full-suite gate. Parallel runs are an optimization, not a substitute:
   if a parallel run fails in a way a serial run does not, the serial result is
   authoritative. See `docs/testing.md` for the current status of parallel
   execution.

## 5. Pull requests and issues

- Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`). Reference the epic
  and stories the PR delivers (e.g. `E3`, `E3-S1…S6`).
- Epic PRs must show the full-suite gate green and tick the DoD items.
- Use the issue templates under `.github/ISSUE_TEMPLATE/` for bugs, feature
  requests, and story tracking.
- Commit messages follow the existing convention:
  `type(scope): summary (E<n>-S<m>)` — e.g.
  `feat(agents): add agent runtime with fail-closed budgets (E2-S3)`.

## 6. Documentation

- Story-level: the DoD (`docs/v2_platform/templates/dod_checklist.md`) requires
  updating docs for what shipped — keep `docs/` and the tracking files
  (`docs/v2_platform/progress.md`, the epic's phase doc) in sync in the same
  story branch.
- Wave-level: at Alpha/Beta/GA exits, run the
  `docs/v2_platform/documentation_rebuild.md` playbook instead of ad hoc edits.
- Never document an aspiration as a shipped capability; `docs/feature_matrix.md`
  (`default`/`optional`/`stub`/`planned`) is the honesty baseline.

## 7. Architecture decisions

Changes that alter a public contract need an ADR (MINOR) or an RFC + ADR
(MAJOR) under `docs/v2_platform/decisions/` — see
`docs/v2_platform/agent_guide.md` §5.

## 8. License of contributions

By contributing you agree that your contributions are licensed under the
repository's license (see `LICENSE` and `NOTICE`). Redistribution — including
commercial redistribution — must preserve the attribution in `NOTICE`. If you
use this project in academic or published work, please cite it via
`CITATION.cff`.
