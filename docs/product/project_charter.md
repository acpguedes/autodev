# AutoDev Architect Project Charter

## Purpose

AutoDev Architect exists to provide an open source, self-hostable AI software engineering platform that is transparent, auditable, and highly extensible.

## Vision

> Be the reference OSS platform where any AI engineering capability can be plugged in, versioned, isolated and evaluated — from laptop to cluster — with no lock-in.

This is the v2.0 vision statement. The full vision, the 14 measurable
objectives (O1-O14), explicit non-objectives, personas, and end-to-end use
case narratives live in
[`docs/architecture/v2_platform_reference.md` §1](../architecture/v2_platform_reference.md#1-vision-objectives-non-objectives-personas-and-use-cases).
This charter is a short pointer into that document, not a duplicate of it.

## Strategic objective

Become a serious open alternative in the GenAI software delivery category by enabling teams to:

- plan software work;
- inspect repositories;
- propose and apply patches;
- validate code changes;
- preserve governance and traceability.

## Scope

In scope: an architecture where agents, flows, reasoning, routing, skills,
and context/RAG are versioned, pluggable Extension Points around a small,
stable core, runnable local-first and scaling to multi-tenant production
without a rewrite (reference doc §1.1).

Out of scope: AutoDev Architect is not an IDE or code editor, does not
train or host its own foundation models, does not require a cloud or paid
API dependency, does not run code without isolation, and is not primarily
a managed SaaS product. Full non-objectives list: reference doc §1.3.

## Primary user groups

Six personas, detailed with pain points, delivered value, and owning
epics in reference doc §1.4 (end-to-end use case narratives in §1.5):

- **OSS maintainers** — govern contributions and plugin ecosystem health.
- **Individual/self-hosting developers** — evolve code locally, laptop-first.
- **Platform leads** — govern multi-team usage, cost, and access.
- **Self-host operators** — install, operate, and recover their own instance.
- **Plugin authors** — publish agents, skills, and reasoning strategies.
- **Quality/AI engineers** — measure and improve agent and routing quality.

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

Measured against the objectives and targets in reference doc §1.2 (O1-O14)
and the KPIs in §20. At the charter level:

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
