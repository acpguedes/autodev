# E61 — Global Install, AUTODEV_HOME and Layered Configuration

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E60: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E34 (`[project.scripts] autodev`, `autodev doctor`/`bootstrap`/
`upgrade`, `scripts/verify_clean_install.sh`, ADR-015 Accepted)
**Enables:** E62 — a project cannot be discovered relative to the user's
working directory while the tool's own configuration and database are
themselves resolved relative to that same working directory.
**Canonical source:** this document, plus direct inspection of
`backend/config/runtime.py`, `backend/config/settings.py` and
`backend/persistence/database.py` (2026-09-05).

## Context and problem

E34 delivered packaging: `pip`/`pipx`/`uv tool` all resolve the `autodev`
console script identically, `autodev --version` reports package version plus
best-effort commit, and `scripts/verify_clean_install.sh` builds a wheel,
installs it into a fresh virtualenv and runs it from a temporary directory
outside the repository. ADR-015 recorded that as the global installation
strategy and deliberately rejected a `curl | sh` installer.

What E34 did not deliver — and what the v2.0-beta criterion 12 wording
("an installation on a clean environment ... produces an operational
`autodev`") does not by itself force — is an installation that is *independent
of the directory the tool is run from and of the directory the tool's source
lives in*. Four concrete defects, each verified in code:

1. **There is no global data or configuration directory.** `Path.home()`,
   `os.path.expanduser("~")` and `XDG_CONFIG_HOME` do not appear anywhere in
   the Python source. The only occurrence of the string `~/.autodev/config.json`
   in the repository is a mocked route fixture in
   `frontend/e2e/sessions-config.spec.ts:143`. There is nowhere to put
   configuration or memory that belongs to the tool rather than to one project.

2. **The default database is resolved against the launch directory.**
   `DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"`
   (`backend/persistence/database.py:20`). Running `autodev` from a different
   directory silently targets a different database — not an error, not a
   warning, a different set of sessions. `backend/tests/conftest.py:40-104`'s
   autouse `isolated_runtime_config` fixture exists precisely because of the
   sibling hazard, and its docstring says so: an unisolated test "reads the
   developer's own `autodev.config.json` — which may hold a real provider, base
   URL and API key".

3. **Configuration is a single document, not a composition.**
   `RuntimeConfigService` (`backend/config/runtime.py`) loads and saves one
   whole `RuntimeConfig`. There is no global layer to inherit from, and
   `_normalize` collapses a legitimately-empty value into a default via
   `strip() or <default>` — so `""`, and by the same shape `false`/`0` for any
   future boolean/numeric field, cannot be distinguished from "not set". The
   separate `Settings` layer (`backend/config/settings.py`) *does* have a
   documented precedence chain, but its only file source is the single path in
   `AUTODEV_SETTINGS_FILE`, with no default location and no discovery.

4. **Three couplings to the tool's own source tree.**
   `backend/api/main.py:23` pins `.env` to `Path(__file__).resolve().parents[2]`,
   which is the repository root under `pip install -e backend/` and
   `venv/lib/python3.x/` under a wheel install — so on the very installation
   path E34 blessed, `.env` is silently never found.
   `backend/ops/upgrade.py:28` reads `CHANGELOG.md` from the same pinned root,
   degrading to an empty release-notes excerpt off a checkout (guarded, but
   silent). `backend/ops/version.py:63-69` runs `git rev-parse` with
   `cwd=Path(__file__).resolve().parent` — this one is deliberate and
   documented, and is not changed here.

There is also a plain packaging gap: `make install` runs
`pip install -r backend/requirements.txt`, which installs dependencies but
**never registers the `autodev` console script**. The documented ADR-015 path
(`pip install -e backend/`) is not wired into the Makefile at all, and
`scripts/verify_clean_install.sh` is invoked by neither CI nor the Makefile —
`grep` finds it only in its own file and `docs/execution/cli-install.md`.

## Evidence in code and documentation

- `backend/config/settings.py:274-301` — `settings_customise_sources`, the
  documented precedence `init → env → JSON file → dotenv → file secrets`.
- `backend/config/settings.py:303-330` — `_json_settings_source`: reads only
  `AUTODEV_SETTINGS_FILE`, raises on a configured-but-missing path. This is the
  correct failure posture to extend, not to replace.
- `backend/config/runtime.py:16` — `DEFAULT_CONFIG_FILE_NAME = "autodev.config.json"`;
  `:161-179` — `_env_or_cwd_project_root` / `_resolve_config_path`;
  `:199-216` — `_normalize`, the `strip() or <default>` collapse;
  `:144-159` — `apply_to_environment`, which bridges this layer into `Settings`
  by writing `os.environ`.
- `backend/persistence/database.py:20` — the cwd-relative default database URL.
- `backend/api/main.py:23-24` — `_ENV_PATH` and the `load_dotenv(..., override=...)`
  call that makes `.env` win over the JSON settings file in the API process.
- `backend/ops/upgrade.py:28-29` — `_REPO_ROOT` / `_CHANGELOG_PATH`.
- `Makefile` — `install`, `install-backend`, `install-dev`, `venv`; no
  `install-cli`.
- `scripts/verify_clean_install.sh` — runs only `autodev --version` and
  `autodev config validate --profile local`.
- `docs/v2_platform/decisions/ADR-015-global-install-strategy.md` — Accepted;
  hybrid console script + Compose bundle; `curl | sh` explicitly rejected.
- `backend/tests/unit/config/test_settings.py::test_settings_file_loads_below_environment`
  — the single existing precedence test, and the pattern S2 extends.
- `backend/tests/unit/config/test_runtime_config.py::test_config_path_follows_project_root_not_launch_cwd`
  — the only existing test of path resolution, 26 lines.

## Objective

Give the tool an installation and a configuration model that are independent of
both the working directory and the tool's own source tree: one documented global
home for configuration and data, and a per-field composition of internal
defaults, global configuration and project configuration.

## Key result

`autodev` installed from a wheel, run from any directory, reads its
configuration from a documented global home; a project that overrides one field
inherits every other field from the global layer; and reinstalling or upgrading
preserves both.

## Scope

- A single resolver for global paths (`AUTODEV_HOME`, configuration, data,
  default state database).
- Per-field, deeply-merged composition of internal defaults → global
  configuration → project configuration.
- Typed, path-annotated failure on an invalid configuration file.
- Removal of the three source-tree couplings that break a wheel install.
- A Makefile target and documented `~/.local/bin` path that actually register
  the console script.
- Extension of the clean-install verification, and wiring it into CI.
- Documentation of the default paths and how to change them.

## Out of scope

- Project discovery, `.autodev/` and the project layer's *content* — E62. This
  epic defines the composition mechanism and the global layer; E62 supplies the
  project layer and its discovery.
- A `curl | sh` installer or a native binary — rejected in ADR-015 and not
  reopened here.
- Changing `backend/ops/version.py`'s git-commit lookup, which is deliberate.
- Multi-tenancy or credentials storage changes; this epic must not move a secret
  into a new file.

## Stories

### E61-S1 — Source-tree-independent path resolution

Subtasks:
- `E61-S1-T1`: a new `backend/config/paths.py` owning every global path:
  `autodev_home()` (`AUTODEV_HOME`, else `~/.autodev/`), `global_config_path()`,
  `global_data_dir()` and `global_state_db_path()`. One module, pure functions,
  no I/O beyond `mkdir` where a caller explicitly asks for it — so the resolution
  is testable without touching a real home directory.
- `E61-S1-T2`: resolve the default state database against the global data
  directory instead of the launch directory
  (`backend/persistence/database.py:20`). An explicitly configured
  `DATABASE_URL` keeps winning unchanged; only the *default* moves.
- `E61-S1-T3`: fix the two source-tree couplings that break under a wheel
  install: `_ENV_PATH` (`backend/api/main.py:23`) looks for `.env` in the active
  project and in `AUTODEV_HOME` rather than at `parents[2]`, and
  `_CHANGELOG_PATH` (`backend/ops/upgrade.py:28`) reads packaged release notes
  rather than a repository file that a wheel install does not have.

| Criterion | Detail |
| --- | --- |
| Functional | Every global path resolves identically regardless of the process's working directory or whether the code runs from a checkout or a wheel |
| Non-functional | `AUTODEV_HOME` overrides the default; no path is computed from `__file__` for anything a user can configure |
| DoR (specific) | none beyond E34 |
| DoD (specific) | A test that resolves all four paths under `monkeypatch.chdir(tmp_path)` and asserts they do not move; a test that an explicit `DATABASE_URL` still wins |
| Dependencies | E34 |

### E61-S2 — Per-field layered configuration

Subtasks:
- `E61-S2-T1`: compose `internal defaults → global config → project config` by
  **deep merge per field**, so a project that sets only the LLM model inherits
  endpoint, timeout and every other option from the global layer. Nested objects
  merge field by field, not wholesale.
- `E61-S2-T2`: replace `_normalize`'s `strip() or <default>` collapse
  (`backend/config/runtime.py:199-216`) with presence-based resolution, so
  `false`, `0` and `""` are preserved as the values a user actually set. Absence
  is "the key is not in the document", never "the value is falsy".
- `E61-S2-T3`: an invalid configuration file raises a typed error naming **the
  file path and the problem**, and is never treated as absent — extending the
  posture `_json_settings_source` (`backend/config/settings.py:303-330`) already
  takes for `AUTODEV_SETTINGS_FILE`.
- `E61-S2-T4`: writes go only to the layer they came from, and nothing is
  copied automatically from the global layer into a project file — credentials
  in particular. `RuntimeConfigService.save()` must not materialize an inherited
  value into the project document.

| Criterion | Detail |
| --- | --- |
| Functional | A project config setting one field inherits all others; `false`/`0`/`""` survive; an invalid file fails with its path and cause |
| Non-functional | No credential is ever written into a project file by inheritance; `save()` is layer-scoped |
| DoR (specific) | E61-S1 merged |
| DoD (specific) | Precedence test per field following `test_settings_file_loads_below_environment`; a falsy-value test; an invalid-JSON test asserting the path appears in the message; a test that a global API key is not written to the project file on `save()` |
| Dependencies | E61-S1 |

### E61-S3 — Console script installation and data preservation

Subtasks:
- `E61-S3-T1`: a `make install-cli` target running `pip install -e backend/` —
  today `make install` installs dependencies with `-r backend/requirements.txt`
  and never registers the console script, so the documented ADR-015 entry point
  is not reachable from the Makefile at all.
- `E61-S3-T2`: extend `scripts/verify_clean_install.sh` beyond `--version` and
  `config validate` to prove, from a temporary directory outside the repository:
  the global home is created and used, a real command runs, and a **second**
  install over the first preserves the existing `AUTODEV_HOME` contents.
- `E61-S3-T3`: wire the script into CI (`.github/workflows/ci-backend.yml`),
  where it is currently invoked by nothing, so a regression in the wheel install
  path turns a leg red instead of being discovered by a user.

| Criterion | Detail |
| --- | --- |
| Functional | A wheel install run from an unrelated directory works; reinstalling preserves configuration and data |
| Non-functional | The verification runs in CI, not only on demand |
| DoR (specific) | E61-S1 merged (the global home exists to preserve) |
| DoD (specific) | Green CI leg; script output showing the preserved home across two installs |
| Dependencies | E61-S1 |

### E61-S4 — Documentation of paths and precedence

Subtasks:
- `E61-S4-T1`: a new `docs/execution/paths-and-config.md`: the default global
  home, the default data and database locations, what is global versus what is
  per project, and how to change each.
- `E61-S4-T2`: update `docs/execution/cli-install.md` with the
  `~/.local/bin` installation path (`pipx`), `make install-cli`, and the
  statement that the tool does not require its own source directory to run.

| Criterion | Detail |
| --- | --- |
| Functional | Both documents state the real, implemented paths and precedence order |
| Non-functional | English; no aspirational behavior described as present |
| DoR (specific) | E61-S1 and E61-S2 merged |
| DoD (specific) | Documented precedence matches the tests written in E61-S2 |
| Dependencies | E61-S1, E61-S2 |

## Contracts and decisions

### Architectural decisions required

- ADR-015 (Global Installation Strategy) stays Accepted and is **extended, not
  superseded**: the console script remains the mechanism; this epic adds where
  the tool's own state lives. Record the extension in ADR-015's Consequences
  section rather than opening a competing ADR.
- Introducing `AUTODEV_HOME` and moving the *default* database location are a
  MINOR change to a public configuration contract (reference §19.1/§19.3), so a
  lightweight ADR is warranted for the layered-configuration semantics
  themselves — specifically the rule that absence is key-absence and never
  falsiness, since every future field inherits that rule.

### Security and multitenancy

- The global configuration file may hold an LLM API key; it is created `0600`,
  matching the existing `RuntimeConfigService.save()` behavior.
- Inheritance never materializes a credential into a project file (E61-S2-T4).
  A project that needs a different key sets it explicitly.
- `Settings.redacted_dump` and the backup credential redaction (E11) already
  cover the fields this epic moves; no new redaction surface is introduced.

### Migration strategy

- An existing installation keeps working: an explicitly set `DATABASE_URL`,
  `AUTODEV_CONFIG_PATH` or `AUTODEV_SETTINGS_FILE` is unchanged, and only the
  *defaults* move. A pre-existing `./autodev.db` is not migrated automatically —
  moving a user's database silently is worse than leaving it; `autodev doctor`
  reports when a legacy database is found beside the working directory and names
  the command to point at it.
- No schema migration is required in this epic.

### Compatibility and rollback

- Rollback is reverting the default-path change; every explicit configuration
  path continues to behave identically before and after.

## Testing and observability

Tests required:
- Path resolution under an arbitrary working directory, and under `AUTODEV_HOME`.
- Explicit `DATABASE_URL` still wins over the new default.
- Per-field precedence: project sets one field, inherits the rest.
- `false`, `0` and `""` preserved as set values.
- Invalid configuration file raises with path and cause, and is not treated as
  absent.
- A global credential is not written into a project file by `save()`.
- Clean install from a wheel, run outside the repository, twice, preserving data.

Observability:
- `autodev doctor` gains checks for the global home (exists, writable) and for a
  legacy cwd-relative database, using the existing typed-check structure in
  `backend/ops/doctor.py::run_diagnostics` — a failing check must not be a new
  bespoke code path.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Moving the default database orphans an existing user's sessions | Data appears lost after an upgrade | Defaults only; explicit config untouched; `doctor` detects and names a legacy database rather than moving it silently |
| Deep merge introduces surprising inheritance | A project silently inherits a setting the user thought was local | Precedence documented (E61-S4) and asserted per field (E61-S2); `autodev config show` reports the origin layer of each value |
| A global API key leaks into a project file, then into a repository | Credential disclosure | E61-S2-T4 is a tested invariant, not a convention |
| Falsy-value fix changes behavior for an existing config | An empty string that used to fall back now takes effect | Called out in the changelog and in `docs/execution/paths-and-config.md`; the old behavior was a defect, not a contract |

## DoR / DoD

- **DoR:** E34 merged; the layered-configuration ADR written and Accepted.
- **DoD:** all four story DoDs met; every global path resolves independently of
  the working directory and of the source tree; per-field composition proven by
  test including falsy values; clean-install verification green in CI;
  `docs/execution/paths-and-config.md` and `docs/execution/cli-install.md`
  updated; ADR-015 Consequences extended; `docs/v2_platform/progress.md`
  updated.

## Affected documents and code

Documents: `docs/execution/paths-and-config.md` (new),
`docs/execution/cli-install.md`, `docs/execution/upgrade.md`,
`docs/v2_platform/decisions/ADR-015-global-install-strategy.md`,
`docs/v2_platform/progress.md`, `CHANGELOG.md`, `README.md` (quickstart).

Code: `backend/config/paths.py` (new), `backend/config/runtime.py`,
`backend/config/settings.py`, `backend/persistence/database.py`,
`backend/api/main.py`, `backend/ops/upgrade.py`, `backend/ops/doctor.py`,
`Makefile`, `scripts/verify_clean_install.sh`,
`.github/workflows/ci-backend.yml`.
