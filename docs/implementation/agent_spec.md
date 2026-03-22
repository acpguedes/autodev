# Agent Specification

This document defines the target behavior, responsibilities, and structured outputs for AutoDev Architect agents.

---

## Shared principles

All agents should:

- receive structured context;
- produce both narrative and machine-readable output;
- avoid making side effects directly unless explicitly designed to do so;
- preserve traceability between input, reasoning summary, and output;
- support deterministic fallback behavior where practical.

---

## Shared output contract

Every agent result should include:

- `agent_name`
- `summary`
- `status`
- `artifacts`
- `warnings`
- `structured_output`
- `next_recommended_actions`

---

## Planner Agent

### Responsibility
Convert user intent into a structured execution plan.

### Inputs
- user goal
- repository metadata summary
- prior session context

### Outputs
- ordered steps
- assumptions
- risks
- acceptance criteria
- recommended workflow type
- approval requirement flags

---

## Navigator Agent

### Responsibility
Locate the most relevant repository areas for the request.

### Inputs
- repository index
- lexical search results
- semantic retrieval results
- symbol graph

### Outputs
- candidate files
- candidate symbols
- dependency hints
- test files
- confidence notes

---

## Analyzer Agent

### Responsibility
Transform repository context and user intent into a structured change plan.

### Outputs
- impacted areas
- change rationale
- risk assessment
- required updates
- required validations
- unresolved questions

---

## Architect Agent

### Responsibility
Define architectural direction when system-level or greenfield decisions are needed.

### Outputs
- components
- boundaries
- contracts
- technology choices
- quality attributes
- architecture decision notes

---

## Coder Agent

### Responsibility
Generate patch proposals and associated code/test changes.

### Outputs
- unified diff or patch representation
- file operations
- rationale per file
- test additions/updates
- migration notes

### Hard requirements
- prefer minimal localized changes;
- declare uncertainty when confidence is low;
- reference impacted files from navigator/analyzer output.

---

## DevOps Agent

### Responsibility
Generate and evolve delivery and runtime automation assets.

### Outputs
- container changes
- CI/CD changes
- infrastructure template changes
- runtime configuration notes
- deployment risks

---

## Validator Agent

### Responsibility
Define and execute validation.

### Outputs
- command plan
- command results
- logs and artifact references
- failure classification
- rework recommendations

---

## Governor / Policy Agent (future)

### Responsibility
Evaluate actions against configured policies.

### Outputs
- approval requirements
- blocked actions
- policy reasons
- remediation guidance

---

## Reviewer Agent (future)

### Responsibility
Review patch quality before human approval.

### Outputs
- patch review findings
- maintainability concerns
- style and architecture concerns
- suggested improvements

