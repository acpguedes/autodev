# Projects: identity, discovery and isolation (E62)

A **project** is a directory containing a `.autodev/` marker. It is discovered,
persisted per tenant, and every session, retrieved chunk and configuration layer
is scoped to one. See ADR-029 for why `project_id` is a scope *inside* a tenant.

## On-disk layout

```
<project root>/
  .autodev/
    config.json    # per-project config overrides; may be {}
    project.json   # {"name": "...", "git": {"remote_url": ..., "branch": ...}}
```

`git` is recorded when `<root>/.git` is a work tree and omitted otherwise — **a
project without Git is a project**. An unreadable or invalid file raises
`ProjectConfigError` naming the file; it is never treated as "no project".

## Discovery

`backend/projects/discovery.py` walks from the working directory up through its
ancestors and returns the **nearest** directory containing `.autodev/` (nested
projects resolve to the innermost one), or `None`. It is pure path traversal: no
network, no database. `autodev project open` with no argument uses it, and
`autodev doctor` reports the discovered root and how it was found (the `project`
check: marker N levels above, or none).

## The three no-project paths

| Path | API | CLI | Effect |
| --- | --- | --- | --- |
| Open | `POST /v2/projects/open` | `autodev project open [root]` | Validates `.autodev/`, registers and activates |
| Initialize | `POST /v2/projects/init` | `autodev project init [root]` | Adds `.autodev/` to an existing directory, **preserving every file**, then activates |
| Create | `POST /v2/projects/create` | `autodev project create <root>` | Makes the directory (must not exist), initializes it |

`GET /v2/projects` lists projects and the active one; `POST
/v2/projects/{id}/activate` switches. Registering a root needs `project:write`
(admin tier); listing needs `project:read`. Creation/activation emit
`project.created` / `project.activated`. The web UI offers the same three paths
at `/projects` and a selector in the contextual header.

**Initialization is additive only.** It creates missing `.autodev/config.json`
and `.autodev/project.json`; it does not touch other files, does not edit
`.gitignore`, and does not start a flow run (asserted by
`backend/tests/unit/projects/test_project_service.py`).

## Per-session root resolution

`backend/projects/resolution.py::resolve_project_root` is used by
`build_default_orchestrator()` (via `get_orchestrator_v2` and the message job),
`get_project_root_v2`, `get_patch_workspace_root`, `repo_symbols`, the sandbox
policy (`sandbox_policy_from_settings(project_root=...)`) and `mcp_v2`. Order:
session's project → explicit project id → tenant's active project → the
process-wide root. The traversal guard is unchanged in kind
(`resolve()` + `relative_to()`) but evaluated against the session's root.
Pass `project_id` to `POST /v2/sessions` to bind a session; it defaults to the
active project.

## Isolation

Within one tenant, two projects do not share: sessions and their messages
(`SessionMemoryContextProvider` refuses a session of another project),
repository knowledge (`code_chunks.project_id`, applied to the lexical ranker,
the vector ranker and the chunk fetch), or configuration (`.autodev/config.json`
is a layer of the project's own composition only). Proven in
`backend/tests/unit/projects/test_isolation.py`.
