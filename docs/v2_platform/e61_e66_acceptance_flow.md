# E61–E66 Acceptance Flow — Composed Rehearsal (E66-S1)

> Story definition: `docs/v2_platform/phases/e66_acceptance_delivery.md#e66-s1`.
> Follows `beta_acceptance_flow.md` (E35-S2): a composed checklist over evidence
> the program already produced, not a new test suite. Fact-vs-recommendation
> rule (E35-S1-T3): **Met** needs named evidence observed in this rehearsal;
> **Partial** and **Open** are stated where true.

## How this was run (2026-10-04)

One sitting, one checkout, in user order: install → project → change request →
panel → terminal. Commands (backend venv active):

```bash
bash scripts/verify_clean_install.sh                       # install + run outside the checkout
python -m pytest -q backend/tests/unit/orchestrator/test_flow_routing_e63.py \
  backend/tests/unit/flows/test_flow_selection.py backend/tests/unit/terminal/test_terminal.py \
  backend/tests/unit/config/test_paths.py backend/tests/unit/config/test_runtime_config.py \
  backend/tests/unit/projects backend/tests/unit/api/test_projects_v2.py \
  backend/tests/unit/api/test_per_session_project_root.py   # 82 passed
npx playwright test e2e/execution-panel-real-events.spec.ts # 1 passed (frontend/)
```

Limits: the scenario is a scripted composition of automated evidence plus the
real wheel-install script, not a hand-driven session in a browser against a
live model. Rows say so where it matters. No credentials, host names or private
absolute paths appear below.

## Validations

| # | Validation | Epic | Status | Named evidence |
| --- | --- | --- | --- | --- |
| 1 | An implementation task does not trigger a structuring flow | E63 | **Met** | `test_flow_routing_e63.py::test_small_change_in_populated_project_runs_no_bootstrap_and_no_architect`; `test_flow_selection.py::test_gate_eliminates_bootstrap_even_if_model_chooses_it` |
| 2 | A task with no compatible flow executes directly | E63 | **Met** | `test_flow_routing_e63.py::test_no_compatible_flow_executes_directly_and_completes`; `test_flow_selection.py::test_none_is_a_valid_answer` |
| 3 | The panel shows real events and does not duplicate the chat | E64 | **Met** | `frontend/e2e/execution-panel-real-events.spec.ts` (real command + stdout rendered; assistant text absent) — network mocked, so SSE transport against a live backend is not re-proven here |
| 4 | The terminal opens in the correct project and keeps its session | E65 | **Partial** | `test_terminal.py::test_echo_cwd_interrupt_and_reap`, `::test_manager_key_cap_and_project_isolation`, `::test_ws_info_and_io_when_enabled` prove a real PTY bound to the project root, keyed per tenant/project/terminal. Survival across UI navigation (tab mounted in the panel slot) was not driven in a browser in this rehearsal. Terminal is **default off** (`AUTODEV_ENABLE_TERMINAL`) |
| 5 | The tool works from outside its installation directory | E61 | **Met** | `scripts/verify_clean_install.sh` output: wheel built, installed in a fresh venv, `autodev doctor` run from a temp directory outside the checkout, global home preserved across reinstall (also the CI job `clean-install-verification`) |
| 6 | A project is recognized from a subdirectory | E62 | **Met** | `test_discovery.py::test_found_at_depth`, `::test_nested_projects_resolve_to_nearest`; `test_per_session_project_root.py::test_sessions_resolve_different_roots_and_cannot_cross` |
| 7 | Local configuration overrides only the fields it defines | E61 | **Met** | `test_runtime_config.py::test_project_overrides_one_llm_field_and_inherits_the_rest`, `::test_project_overrides_one_repository_field_and_inherits_the_rest`, `::test_empty_string_base_url_is_preserved_over_an_inherited_one` |
| 8 | All three no-project paths work without overwriting existing data | E62 | **Met** | `test_projects_v2.py::test_three_paths_and_listing`; `test_project_service.py::test_initialize_in_place_changes_no_file_and_starts_no_run`, `::test_initialize_keeps_existing_autodev_files`, `::test_create_makes_directory_then_initializes_and_refuses_existing` |

## Findings

- No cross-epic defect surfaced; no behavior was changed by this epic.
- Open follow-up (not a defect): a browser-driven check of validation 4's
  navigation persistence and of validation 3 against a live SSE backend would
  upgrade row 4 to Met. Recorded as backlog, not presumed done.
