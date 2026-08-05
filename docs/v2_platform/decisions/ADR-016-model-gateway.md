# ADR-016: AutoDev-Owned Provider-Neutral Model Gateway Boundary

- **Status:** Accepted
- **Date:** 2026-08-05
- **Authors:** AutoDev contributors
- **Related epic:** E2-S6
- **Supersedes/Relates to:** ADR-003

## Context

E2-S4 introduced a small synchronous `LLMProvider` protocol and an offline stub, while
the v1-facing path still creates LangChain chat models directly. That split is useful
for compatibility but does not provide one durable contract for normalized messages,
tool calls, structured output, streaming, usage/cost telemetry, capabilities, typed
errors, retries, and fallback policy.

AutoDev needs that boundary before adding provider adapters. The core must remain
self-hostable and usable offline, and manifests must never contain API keys, access
tokens, passwords, or other credentials. Provider SDK payloads are not stable enough
to become persisted domain state or public agent contracts.

## Decision

AutoDev owns a provider-neutral model gateway boundary under `backend.llm`. Its public
surface consists of immutable Python contracts containing only JSON-like values and a
structural `ModelProvider` protocol. Replaceable adapters translate those contracts to
and from provider SDKs. The existing LangChain factory remains a compatibility adapter,
not the domain contract.

Agent manifest schema 2.1 adds typed `model` selection, capability requirements,
bounded retries, fallback conditions, and aggregate call/token/cost limits. Schema 2.0
remains valid. Legacy string `policy.model` is interpreted as a provider-inheriting
alias, but a manifest cannot declare both forms. Model configuration is validated
before execution and recursively rejects credential-like keys.

Provider credentials remain in the existing settings/secret boundary and are passed
to adapters at composition time. They are excluded from manifests, normalized
requests, responses, telemetry, and error messages. Offline operation uses an in-tree
stub adapter and must not require a proxy, SaaS control plane, network call, pricing
catalog, or provider SDK.

E2-S6 is additive to E2: it does not replace agent IO, runtime budgets, permission
mediation, or the E2-S4 protocol until adapters and runtime integration are validated.
The old path can coexist during migration.

External coding agents are not model providers. Their filesystem/process lifecycle,
interactive protocol, workspace isolation, patch semantics, and approvals require a
future `CodingAgentHarness` abstraction. They must not be hidden behind `ModelProvider`
or granted model-gateway credentials implicitly.

## Alternatives considered

1. **Direct internal provider adapters without a shared AutoDev contract** — minimal
   initial code, but leaks SDK types and duplicated retry, telemetry, and policy
   behavior into agents. Rejected because it weakens portability and governance.
2. **Embedded LiteLLM** — broad provider coverage behind an OSS library and no separate
   service. Deferred because it adds a large dependency and its vocabulary would
   become the de facto domain contract before AutoDev's required semantics stabilize.
3. **LiteLLM Proxy** — central routing, budgets, and observability across processes.
   Deferred because a required service harms offline/local-first operation, expands the
   security and deployment surface, and is disproportionate for the E2 correction.
4. **Existing LangChain factory adapter** — preserves current integrations and is
   useful as a migration adapter. Rejected as the core boundary because LangChain
   objects do not define AutoDev's durable usage, error, capability, fallback, or
   streaming semantics.

## Consequences

- **Positive:** Agents and workflows depend on stable AutoDev types; adapters remain
  replaceable; stub-only deployments work offline; telemetry and errors have one
  normalized vocabulary; credentials stay outside manifests and persisted contracts.
- **Negative / trade-offs:** AutoDev must maintain adapters and normalization logic;
  some provider-specific features require explicit additive contract evolution; LiteLLM
  integration, if later justified, must be implemented as an adapter.
- **Security:** Recursive sensitive-key rejection reduces accidental secret persistence,
  but runtime secret injection, log redaction, and adapter-specific threat reviews remain
  mandatory. Gateway policy never expands agent tool, network, or tenant permissions.
- **Self-hosting:** No new infrastructure or paid dependency is required. Proxy routing
  remains optional future deployment architecture, not a prerequisite.
- **Contract impact:** `agent.yaml` gains an additive 2.1 schema; 2.0 and the legacy
  string alias remain accepted. The E2 tracker temporarily reopens at 5/6 stories.

## Rollback plan

Stop selecting schema 2.1 model configuration and route calls through the existing
E2-S4 provider or LangChain factory path. Because the new manifest field and contracts
are additive and no persisted data migration is required, existing 2.0 manifests keep
working unchanged. Remove adapters and gateway composition only after confirming no
2.1 manifests are active; retain this ADR as the historical decision record.

## References

- `docs/v2_platform/phases/e2_agent_framework.md` — E2-S6 scope and non-goals.
- `docs/architecture/v2_platform_reference.md` — platform contract and OSS principles.
- ADR-003 — Agent Manifest and Initial Capability Vocabulary.
