# Flow builder screen — E17-S6

Route: `frontend/app/flows/page.tsx` (`/flows`). Realigns the existing
E10-S3 visual flow editor (`frontend/components/flow/`) with the "Flow
builder" view from the Execution Control Center redesign prototype
(`layout_prototype_brainstorm/` §5.4), inside the E15 shell
(`ShellHeaderPortal`) and against the E16 `/v2` flow endpoints via
`frontend/lib/api_v2.ts`. This was a realignment, not a rebuild: the graph
canvas, deterministic `flow.yaml` round-trip, and validation panel from
E10-S3 are preserved.

## Layout (three columns)

- **Left palette** (`components/flow/FlowPalette.tsx`, a
  `role="group"[aria-label="Flow palette"]`), sections fed by static
  editor-only content in `lib/flow/paletteItems.ts`:
  - **Agents**: the 8 built-in agent types (`AGENT_PALETTE_ITEMS`) —
    Planner, Navigator, Analyzer, Coder, Validator, Reviewer, Docs,
    Security. Clicking one seeds an `agent` node with a placeholder `ref`
    (e.g. `autodev/agent-coder`), editable afterwards in the inspector.
  - **Flow control**: blocks (`CONTROL_PALETTE_ITEMS`) — Conditional, Loop
    (`map`), Human approval, Parallel (join) (`map`, `maxParallel: 4`),
    Prompt/Step (`supportsPreviousOutput`: seeds `input.previous` with
    `{{ nodes.<selected>.output }}` when a node is selected), Start
    (`preventIncomingEdge`: never wired from the selected node), End.
  - When a node is selected on the canvas, inserting a palette item also
    creates an edge from the selected node to the new one (except Start).
- **Center canvas** (`components/flow/FlowCanvas.tsx`, a
  `role="group"[aria-label="Flow graph canvas"]`): draggable nodes on a
  dotted grid with curved edges and branch (guard) labels; nodes carry a
  type badge and connector dots per side (`CONNECTOR_SIDES`).
- **Right inspector** (`components/flow/NodeInspector.tsx`): type-specific
  fields per node kind — `ref` only for `REF_NODE_TYPES`
  (`agent`/`skill`/`tool`/`subflow`/`map`), prompt for `human`, `over`/
  `maxParallel` for `map`, predicate/guard editing per outgoing edge, edge
  add/remove, and timeout target.
- **Actions** (`components/flow/FlowEditor.tsx` header): **Clear** (empties
  the canvas, confirmed by toast) and **Save**. Save gates on local
  validation (`lib/flow/validate.ts::validateFlow`), then re-checks the
  manifest server-side with `validateFlowV2` and reports the outcome via
  toast — invalid manifests resolve with `valid: false` rather than throw,
  and nothing is persisted by validation alone.

## API contract (E16)

| Client function | Endpoint |
| --- | --- |
| `listFlowsV2` | `GET /v2/flows` (catalog metadata; not yet a canvas loader) |
| `validateFlowV2` | `POST /v2/flows/validate` (non-mutating schema check) |
| `registerFlowV2` | `POST /v2/flows` (persist a new flow version) |

## Accessibility

- Canvas nodes are keyboard-operable: focusable, moved with the arrow keys
  (`ArrowLeft/Right/Up/Down` position deltas), with per-node `aria-label`s
  describing type and label.
- Inspector selects and edge controls carry explicit `aria-label`s
  (`Node type`, `Edge N target`, `Edge N guard type`, `Edge N predicate`,
  `Remove edge to <id>`, `New edge target`, `Timeout target node`); the
  raw YAML view is labeled `flow.yaml source`.
- Palette entries are native `button`s grouped under labeled sections; no
  custom key handling required.

## Testing

- Unit: `frontend/lib/flow/validate.test.ts` (manifest validation) plus the
  existing E10-S3 round-trip coverage under `lib/flow/`.
- Storybook: `components/flow/FlowPalette.stories.tsx` and
  `components/flow/flow-canvas.stories.tsx`, run under the `storybook`
  Vitest project for automated a11y checks (axe).
- e2e: `frontend/e2e/flow-builder.spec.ts` covers the three-column layout,
  inserting a Coder agent from the palette (auto-connected to the selected
  node), Clear emptying the canvas, and Save validating the manifest with
  the outcome reported via toast.
