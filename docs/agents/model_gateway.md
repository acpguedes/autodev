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
| 3 | Global default | `PUT /v2/provider-config`, overridable by `LLM_MODEL` |

If none of the three yields a model, the run fails with `provider_not_configured`.
That is deliberate: the gateway never guesses a model.

Only an **omitted provider** inherits from the global default. Fallback policy is
never merged from a lower-precedence source — if you declare a model, you declare its
recovery policy too.

## Global configuration

The provider and the global default model are owned by the versioned Control Plane
API and persisted in the runtime configuration:

```http
PUT /v2/provider-config
{"llm": {"provider": "openai", "model": "gpt-4o-mini"}}
```

`LLM_MODEL` remains available as an environment-only override of the model, for
deployments that never write `autodev.config.json`:

```bash
LLM_MODEL=gpt-4o    # overrides the persisted model when non-empty
```

The override is safe because `RuntimeConfigService.apply_to_environment` exports the
configured model as `OPENAI_MODEL` and **never** as `LLM_MODEL` — an API update cannot
clobber it. The provider is read only from the runtime configuration:
`Settings.llm_provider` is cached on first read, before `apply_to_environment` mutates
the environment, so it is a stale snapshot by construction.

`provider: stub` is fully offline and needs no credentials or network. It is the
default and remains first-class — see **Composition** for what that means in practice.

## Composition

`backend/llm/composition.py` is the composition root. It builds the process-wide
registry and gateway and hands them to the agent runtime:

| Function | Role |
| --- | --- |
| `get_model_gateway()` | The shared gateway, or `None` when running offline |
| `get_global_model_config()` | The effective global default (precedence 3 above) |
| `build_agent_runtime()` | An `AgentRuntime` carrying both |
| `reset_model_composition_cache()` | Invalidation, called by every config-write surface |

`AgentNodeHandler` uses `build_agent_runtime()` as its default, so agents executed by
the flow engine reach the gateway without any caller doing wiring. An explicitly
injected runtime always wins, which is how tests and embedded deployments override it.

**`provider: stub` composes no gateway.** `StubModelProvider` is keyed by model name
and raises for any model it was not scripted with, so it is a test double rather than a
runtime provider. With no gateway, `call_llm` keeps its existing branch into
`StubLLMProvider`, which answers any prompt deterministically and offline. An
unrecognized provider id degrades the same way rather than breaking every run.

The module is deliberately **not** re-exported from `backend/llm/__init__.py`:
`backend.config.runtime` imports `backend.llm.factory` at module scope, so re-exporting
would close an import cycle. Import it by full path.

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
  unsupported behavior fails closed; they are not probed from the provider. They are
  also declared **per adapter, not per model**: `LangChainModelProvider` declares the
  same four capabilities for every model of a provider, so preflight passes for a model
  that cannot actually do tool calling and the request fails later, inside the call.
- **`timeoutSeconds` reports, it does not bound.** The check runs on the elapsed
  duration *after* the provider call returns, so it converts a slow call into a typed
  `timeout` error and charges the attempt — but it cannot interrupt a hung provider.
  The real bound comes from the adapter: `LangChainModelProvider` forwards
  `request_timeout` to the HTTP client. Providers without that forwarding — the legacy
  adapter, the stub, any third-party `ModelProvider` — have no bound at all.
- **`retries` only fires for codes also listed in `fallbackOn`.** Retry is evaluated as
  "the error is in `fallbackOn` *and* attempts remain", so `retries: 2` with an empty
  `fallbackOn` yields exactly one attempt. List the codes you want retried.
  `ModelGatewayError.retryable` is informational only — no policy reads it.

## Rolling back

Set the provider back to `stub`:

```http
PUT /v2/provider-config
{"llm": {"provider": "stub", "model": "irrelevant"}}
```

No code change and no restart: the write invalidates the composition cache, the next
agent run composes no gateway, and `call_llm` returns to the legacy `StubLLMProvider`
path. The manifest field and the contracts are additive and no persisted data migrates,
so 2.0 manifests keep working unchanged either way.
