# Model Gateway

AutoDev owns a provider-neutral boundary for model calls under `backend.llm`.
Agents select a model declaratively; the gateway resolves it, checks capabilities
before invoking anything, applies opt-in retry and fallback, enforces call/token/cost
ceilings, and emits telemetry — all through AutoDev's own types.

The decision behind this boundary is [ADR-016](../v2_platform/decisions/ADR-016-model-gateway.md).

## Selecting a model

Three sources, in strict precedence order:

| Precedence | Source | Set by |
| --- | --- | --- |
| 1 (highest) | Execution override | `AgentRuntime.run(..., model_override=...)` |
| 2 | Agent manifest | `model:` in `agent.yaml` (schema 2.1) |
| 3 | Global default | `LLM_PROVIDER` + `LLM_MODEL` |

If none of the three yields a model, the run fails with `provider_not_configured`.
That is deliberate: the gateway never guesses a model.

Only an **omitted provider** inherits from the global default. Fallback policy is
never merged from a lower-precedence source — if you declare a model, you declare its
recovery policy too.

## Global configuration

```bash
LLM_PROVIDER=stub      # stub | openai | ollama
LLM_MODEL=             # global default model; empty means "no global default"
```

`LLM_MODEL` empty is a valid, safe configuration: agents that declare their own model
work, and agents that do not fail explicitly instead of silently picking one.

`LLM_PROVIDER=stub` is fully offline and needs no credentials or network. It is the
default and remains first-class.

## Agent manifest (schema 2.1)

Schema 2.0 manifests remain valid and need no migration. Schema 2.1 adds a top-level
`model` block:

```yaml
schemaVersion: "2.1"
id: acme/reviewer
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
  maxTokens: 2048
  timeoutSeconds: 30
  retries: 1
  requiredCapabilities: [text, tool_calling]
  fallbackOn: [rate_limit, unavailable]
  fallback:
    - provider: ollama
      name: llama3.1
  limits:
    maxCalls: 5
    maxTotalTokens: 20000
    maxCostUsd: 0.50
```

The legacy string form `policy.model` still works as a provider-inheriting alias.
Declaring both forms is rejected rather than resolved by precedence.

Credentials are rejected in manifests, recursively and by key name. They belong in
settings, injected at composition time.

## Capabilities and errors

Capabilities are exactly:

`text` · `streaming` · `tool_calling` · `structured_output`

Error codes are exactly:

`provider_not_configured` · `unsupported_capability` · `authentication` ·
`invalid_request` · `rate_limit` · `timeout` · `unavailable` · `budget_exceeded` ·
`provider_error`

Both vocabularies are closed. Capability requirements are checked against the
provider's declaration **before** any call, so an unsupported request fails without
spending money.

## Fallback

Fallback is opt-in and governed:

- it fires only for the exact codes listed in `fallbackOn`;
- capability-based fallback additionally requires `unsupported_capability` in that list;
- targets are tried in declared order;
- **streaming never switches provider after output has reached the caller**, so a
  response is never a splice of two models.

## Observability

Each attempt produces a span (`autodev.model.call`) carrying agent, provider, model,
latency, tokens, estimated cost, fallback index, and a stable error code — never
prompts and never credentials.

`AgentRunResult.metrics` aggregates the run: `model.attempts`, `model.failures`,
`model.latency_ms`, alongside the existing token and cost totals.

## Known limitations

These are real and tested, not aspirations:

- **Cost ceilings need reported cost.** `maxCostUsd` acts on provider-reported or stub
  estimates. A provider that reports no cost contributes zero, so a cost ceiling
  cannot fail closed on it. `maxCalls` and `maxTotalTokens` remain enforceable and are
  the reliable guardrails there.
- **Streaming cost enforcement is not pre-emptive.** Real providers report usage and
  cost on the terminal chunk, after content has been delivered. The gateway fails
  closed as soon as it learns the cost, but cannot withhold content it had no reason
  to block. Use `maxCalls` or a non-streaming call when overspend must be impossible.
- **Tool calling combined with structured output is provider-dependent.** The adapter
  forwards `tools` only to providers that declare the parameter explicitly
  (`ChatOpenAI` does; the LangChain base shape does not). Where it cannot be
  guaranteed, the request fails with `unsupported_capability` rather than silently
  dropping the tools.
- **Streaming plus structured output is unsupported** by the LangChain adapter and
  fails explicitly.
- **No pricing catalog.** Cost is whatever the provider or stub reports; AutoDev does
  not price tokens itself.
- **Capabilities are declared, not discovered.** They are registered per adapter so
  unsupported behavior fails closed; they are not probed from the provider.

## Rolling back

Stop selecting schema 2.1 model configuration and route calls through the existing
provider/LangChain factory path. The manifest field and the contracts are additive and
no persisted data migrates, so 2.0 manifests keep working unchanged.
