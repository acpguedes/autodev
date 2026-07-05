# Flow Manifest Specification (`flow.yaml`)

> Delivered by **E3-S1**. Canonical background:
> `docs/architecture/v2_platform_reference.md` §18.6 (E3) and Appendix (C).
> Machine-readable schema: `backend/flows/schemas/flow.schema.json`.
> Reference implementation: `backend/flows/manifest.py` (parsing/field rules),
> `backend/flows/graph.py` (graph rules), `backend/flows/expressions.py`
> (predicates and bindings). Worked example:
> `docs/v2_platform/templates/manifests/flow.yaml.example`.

A flow is a **versioned, declarative graph** of nodes that orchestrates agents,
skills, tools, and humans. The Orchestration Engine (E3-S2+) executes it with
durable, resumable, observable state. Flows are configuration, not code: the
whole definition lives in `flow.yaml`.

## Top-level document

| Field | Required | Meaning |
| --- | --- | --- |
| `schemaVersion` | yes | Manifest schema version; currently `"1"`. |
| `id` | yes | `namespace/name`, kebab-case (e.g. `autodev/flow-feature-delivery`). |
| `version` | yes | Flow SemVer `MAJOR.MINOR.PATCH`. |
| `hostApi` | yes | Host API compatibility range, e.g. `">=2.0 <3.0"`. |
| `name`, `description` | no | Display metadata. |
| `triggers` | no | What starts a run: `message`, `webhook`, `cron` (needs `schedule`), `event` (needs `on`). |
| `input`, `output` | no | JSON Schemas for run input/consolidated output (carry their own `schemaVersion`). |
| `defaults` | no | `retries` and `timeoutSec` applied to nodes that do not override them. |
| `nodes` | yes | The graph's nodes (see below). |
| `edges` | yes | Transitions between nodes (see below). |
| `budgets` | no | Fail-closed run budgets: `maxCostUsd`, `maxWallClockSec`, `maxTokens`. Defaults: 10.0 USD / 3600 s / 2,000,000 tokens. |

Budgets always exist: omitted budgets fall back to the safe defaults above and
the engine **fails closed** when a run exceeds them (reference doc Principle
2.5). Flow budgets complement — never replace — per-agent budgets from E2.

## Node types

Canonical vocabulary (reference doc §3): `agent`, `skill`, `tool`,
`conditional`, `human`, `subflow`, `map`.

| Type | Required fields | Notes |
| --- | --- | --- |
| `agent` | `ref` | Executes an agent resolved from the Agent Registry (E2). |
| `skill` | `ref` | Deterministic or LLM-assisted reusable function (E6). |
| `tool` | `ref` | Low-level capability invocation. |
| `conditional` | — | Pure routing node; **every** outgoing edge must be guarded and there must be at least two. `ref`/`input` are not allowed. |
| `human` | `prompt` | Pauses the run for a decision/edit (E3-S4). Optional `form` (JSON Schema of the decision), `timeoutSec`, `onTimeout` (target node id of the `on: timeout` edge). |
| `subflow` | `ref` | Runs another flow as a child (E3-S5). |
| `map` | `ref`, `over` | Fans out `ref` over the collection produced by the `over` expression; `reduce` (currently `collect`) aggregates; optional `maxParallel` (E3-S5). |

Common optional fields: `input` (bindings, see Expressions), `timeoutSec`,
`retries` (`maxAttempts` >= 1, `backoff: fixed|exponential`,
`initialDelaySec` >= 0).

`ref` format: `namespace/name[@version-or-range]` — `autodev/agent-coder@2.1.0`,
`autodev/skill-apply-patch@>=1.0 <2.0`, or unversioned (`*`). Ranges use PEP
440-compatible specifiers joined by spaces; resolution against registries uses
`backend.flows.manifest.version_in_range`.

## Edges

```yaml
edges:
  - from: "plan"
    to: "code"                        # unconditional
  - from: "gate"
    to: "review"
    when: "{{ nodes.lint.output.ok == true }}"   # predicate over run state
  - from: "review"
    to: "escalate"
    on: "timeout"                     # named signal (human SLA expiry)
```

- An edge is **guarded** when it declares `when` (predicate) or `on` (signal);
  `when` and `on` are mutually exclusive on one edge.
- Signal vocabulary: `timeout`, legal only on edges leaving `human` nodes; the
  node then needs `timeoutSec`, and its `onTimeout` (when present) must match
  the edge's target.
- YAML 1.1 note: PyYAML parses a bare `on` key as boolean `true`; the parser
  tolerates this, but quoting (`"on":`) is the recommended spelling.

## Graph validity rules

An invalid graph is rejected as a whole (`validate_flow_manifest` returns every
error found, not just the first). Rules enforced by `backend/flows/graph.py`:

1. Node ids are unique, kebab-case.
2. Every edge endpoint references a declared node.
3. Exactly **one entry node** (no incoming edges) and at least one terminal
   node (no outgoing edges).
4. Every node is reachable from the entry node.
5. **No unconditional cycles**: a cycle is legal only if at least one of its
   edges is guarded (rework loops); a cycle of unguarded edges can never
   terminate and is rejected.
6. `conditional` nodes: >= 2 outgoing edges, all guarded. Other nodes: at most
   one unguarded outgoing edge (no implicit parallel fan-out; use `map`).
7. Human-node timeout consistency (see Edges above); `onTimeout` is only legal
   on human nodes.
8. Every `when` predicate and `{{ ... }}` binding must compile, and may only
   reference known state roots (see next section).

## Expressions and bindings

Predicates and input bindings use a small, safe expression language
(`backend/flows/expressions.py`) — path lookups, literals (`'str'`, numbers,
`true`, `false`, `null`), comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`), and
`and`/`or`/`not`. No function calls, no arithmetic, no attribute access, no
`eval`. Ordering comparisons require numbers and otherwise raise; missing
paths resolve to `null` so optional state is testable.

State roots addressable from a flow:

- `flow.input.<field>` — the run input. When the flow declares an `input`
  schema with `properties`, referenced fields must be declared.
- `nodes.<node-id>.output.<path>` — a previous node's output. The node must
  exist and only `output` is addressable. Kebab-case ids work both as
  `nodes.my-node.output` and `nodes['my-node'].output`.
- `item` — the current element, available only inside `map`-node bindings.

Bindings that are exactly one template (`patch: "{{ nodes.code.output.patch }}"`)
preserve the value's type; templates embedded in longer strings interpolate as
text. Mappings and lists render recursively.

## Versioning

Flows are SemVer-versioned artifacts (reference doc §19.1): breaking changes to
a flow's contract (input/output schema, meaning of its output) bump MAJOR;
adding nodes/edges without breaking the contract bumps MINOR; fixes bump PATCH.
The manifest's `schemaVersion` versions the **manifest format** itself and is
pinned to `"1"`. Registration and storage of versioned flows arrive with the
flow registry in E3-S2.

## Python API

```python
from backend.flows import load_flow_manifest, validate_flow_manifest

manifest = load_flow_manifest("flow.yaml")          # raises ValueError on invalid
result = validate_flow_manifest(raw_dict)            # returns errors instead
if result.valid:
    entry = result.manifest.entry_node()
```

The `FlowManifest` contract is exported through the SDK
(`backend.sdk.contracts.FlowManifest`, SDK contract version 1.1.0).

## Decision records

- RFC-002 — Flow manifest specification (`docs/v2_platform/decisions/RFC-002-flow-yaml-spec.md`).
- ADR-004 — Flow manifest and node-type vocabulary (`docs/v2_platform/decisions/ADR-004-flow-manifest-and-node-types.md`).
