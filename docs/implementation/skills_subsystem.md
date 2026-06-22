# Skills subsystem

Reusable, composable capabilities that agents (and operators) can discover and invoke.

## Core (`backend/skills/`)

- `base.py` — `SkillContext(inputs, project_root)`, `SkillResult(content, data, success)`,
  and the `Skill` protocol (`name`, `description`, `run(context) -> SkillResult`).
- `registry.py` — `register_skill(name, description)` decorator, `get_registry()`,
  `discover_skills()` (imports built-ins so they self-register), and
  `invoke_skill(name, context)`.
- `builtin/` — deterministic, dependency-free skills:
  - `summarize_diff` — counts changed files and added/removed lines in a unified diff.
  - `extract_symbols_lexical` — top-level `def`/`class` names via regex (no tree-sitter).
  - `render_checklist` — renders a Markdown checklist from a list of items.

Skills are pure and deterministic, so they run identically under the `stub` provider and
require no paid model.

## HTTP API (`backend/api/routers/skills.py`)

- `GET /skills` — list discovered skills (`name`, `description`).
- `GET /skills/{name}` — describe a single skill (404 if unknown).
- `POST /skills/{name}/invoke` — body `{"inputs": {...}}`; returns the `SkillResult`.

```bash
curl localhost:8000/skills
curl -X POST localhost:8000/skills/summarize_diff/invoke \
  -H 'Content-Type: application/json' \
  -d '{"inputs": {"diff": "--- a\n+++ b\n@@\n+added\n-removed\n"}}'
```

## CLI (`backend/cli_plugins/skills.py`)

```bash
autodev skills list
autodev skills invoke summarize_diff --input diff="--- a
+++ b
+x
-y"
```

## Extending

Add `backend/skills/builtin/<name>.py` with a `@register_skill("<name>", "...")` class
implementing `run(context)`, and import it from `backend/skills/builtin/__init__.py`. The
API and CLI surface it automatically.
