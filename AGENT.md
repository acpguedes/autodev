# AGENT.md

## AutoDev Architect agent operating guide

This file is intended for autonomous or semi-autonomous software agents working on this repository.

### Project identity
AutoDev Architect is not just a chat application. It is intended to become an open source control plane for AI-assisted software engineering workflows.

### What good changes look like
Good changes usually improve one or more of the following:

- durability of state;
- clarity of workflow state;
- repository intelligence;
- patch generation quality;
- validation depth;
- observability;
- self-hostability;
- contributor clarity.

### Preferred implementation style
- small focused changes;
- strongly typed contracts;
- explicit schemas and state transitions;
- clear docs for major behavior changes;
- minimal operational overhead where possible.

### Preferred product direction
Build toward:
- plan approval workflows;
- patch-first engineering;
- sandbox validation;
- local model support;
- OSS-friendly deployment.

### Avoid
- magic hidden behavior in prompts;
- tightly coupling the system to one external provider;
- unreviewable broad rewrites;
- adding infrastructure complexity without roadmap justification.

### If architecture is unclear
Use these docs as source of truth:
1. `README.md`
2. `DESCRIPTION.md`
3. `docs/architecture/target_architecture.md`
4. `docs/implementation/implementation_strategy.md`
5. `docs/architecture/stack_decisions.md`

