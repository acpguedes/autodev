# Agent Manifest (`agent.yaml`)

Agents in v2 are plugins with a second manifest, `agent.yaml`, referenced by the
plugin's `agent` extension point. The manifest is declarative: identity,
capabilities, IO schemas, permissions, policy, budgets, and the Python handler are
declared outside prompt text.

## Required fields

- `schemaVersion`: `"2.0"`.
- `kind`: `Agent`.
- `id`: `namespace/name` in kebab-case, for example `autodev/agent-coder`.
- `version`: SemVer `MAJOR.MINOR.PATCH`.
- `hostApi`: compatibility range such as `>=2.0 <3.0`.
- `capabilities`: one or more versioned capabilities from ADR-003.
- `io`: typed input and output JSON schemas with a SemVer `contractVersion`.
- `entrypoint`: Python handler reference in `module:callable` form.

## Safe defaults

If `budgets` is omitted, the validator applies the Alpha default:

```yaml
budgets:
  tokens: { input: 120000, output: 16000 }
  costUsd: 0.75
  wallClockSeconds: 180
  maxSteps: 24
  maxToolCalls: 40
  onExceeded: fail-closed
```

If `permissions.network` is omitted, it defaults to `none`. Tools and skills are
empty by default, so the Agent Runtime denies access unless permissions are declared.

## Example

```yaml
schemaVersion: "2.0"
kind: Agent
id: autodev/agent-coder
version: 1.0.0
hostApi: ">=2.0 <3.0"
capabilities:
  - id: code.implementation
    version: 1.0.0
    level: primary
  - id: code.refactor
    version: 1.0.0
    level: secondary
io:
  contract: autodev/coder-io
  contractVersion: 1.0.0
  input:
    $ref: ./contracts/coder.input.schema.json
  output:
    $ref: ./contracts/coder.output.schema.json
  onInvalidOutput: fail
permissions:
  network: none
  tools:
    - id: fs.read
    - id: patch.apply
      constraints: { dryRunFirst: true }
  skills:
    - id: autodev/skill-unified-diff
      versionRange: ">=1.0 <2.0"
entrypoint:
  runtime: python
  ref: autodev_agent_coder:CoderAgent
```

`backend.agents.manifest.load_agent_manifest()` resolves local `$ref` schema files.
`validate_agent_io()` rejects input or output that violates the declared schema,
including undeclared fields when `additionalProperties: false` is set.
