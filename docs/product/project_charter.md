# AutoDev Architect Project Charter

## Purpose

AutoDev Architect exists to provide an open source platform for AI-assisted software engineering that is transparent, auditable, extensible, and self-hostable.

## Strategic objective

Become a serious open alternative in the GenAI software delivery category by enabling teams to:

- plan software work;
- inspect repositories;
- propose and apply patches;
- validate code changes;
- preserve governance and traceability.

## Intended outcomes

- Reduce the time between a request and a validated patch.
- Improve quality through structured validation and review gates.
- Support both greenfield creation and existing repository evolution.
- Enable organizations to self-host critical AI engineering workflows.

## Primary user groups

- OSS maintainers.
- Platform engineering teams.
- Developer productivity teams.
- Self-hosting and privacy-sensitive organizations.
- Applied AI engineering researchers.

## Product constraints

- Core deployment path must be viable with open source infrastructure.
- Paid APIs may be supported, but cannot be the only path.
- Critical actions must support explicit approval and auditing.
- Repository changes must be patch-first and review-friendly.

## Quality bar

A strong release should provide:

- persistent session state;
- structured run states;
- repository intelligence;
- patch generation and validation;
- isolated execution;
- observability;
- contributor and operator documentation.

## Success metrics

- Time from user request to validated patch.
- Plan approval rate.
- Patch acceptance rate.
- Validation pass rate.
- Mean iteration count until success.
- Cost per successful change.
- Self-hosted deployment success rate.
- Contributor onboarding time.

## Governance principles

- Explain decisions where possible.
- Prefer structured outputs over free-form text for machine actions.
- Preserve run history and artifacts.
- Make policies configurable by repository or workspace.
- Keep architecture modular and replaceable.

