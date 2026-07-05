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

### v2 platform work
The v2.0 platform rewrite (plugin core, agent framework, flow engine — epics E0–E13)
is the active development track; E0–E2 are complete. Before picking up any
`E<n>-S<m>` story, read `docs/v2_platform/agent_guide.md` and check
`docs/v2_platform/progress.md`. The branching, docstring/type-hint, and testing
rules in `CONTRIBUTING.md` are mandatory.

### If architecture is unclear
Use these docs as source of truth:
1. `docs/architecture/v2_platform_reference.md` (canonical v2 design)
2. `docs/v2_platform/progress.md` (what has actually landed)
3. `README.md`
4. `DESCRIPTION.md`
5. `docs/architecture/target_architecture.md` (historical v1 target)
6. `docs/architecture/stack_decisions.md`

