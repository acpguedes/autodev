# Isolation Violation Incident Runbook (E35-S3)

Extends `docs/v2_platform/runbooks/e11_incident_response.md` §4 (Sandbox
containment) with the **E32 execution-environment layer**
(`backend/environments/`) specifically: backend/profile selection, network/
filesystem policy, and the provision → execute → collect → teardown
lifecycle. §4 stops the underlying sandboxed process; this runbook stops
*new environment provisioning at the abstraction layer* and gives you the
audit trail to reconstruct what a specific run's environment actually did.

Trigger: a suspected escape from the isolated environment, an
`environment.access.denied` event for a destination that should never have
been attempted in the first place (i.e. the policy caught something real,
not routine denial-by-design), or any report that isolated execution
behaved outside its documented contract (`docs/environments/beta_isolation.md`).

## 1. Immediate containment — stop new provisioning

Force every subsequent environment resolution to the fail-closed sentinel,
without touching in-flight validation jobs (that is §4's job, run it too if
the suspected escape is active right now):

```bash
# Any unrecognized value resolves to UnavailableBackend (backend/environments/registry.py) —
# "unavailable" is used here because it is self-documenting in a status dump.
export AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable
docker compose -f infrastructure/docker-compose.yml restart backend
```

With this set, every new `EnvironmentManager.provision()` call resolves to
`UnavailableBackend`, which denies outright — no task gets a new isolated
environment until the setting is reverted. This is a coarser, layer-above
stop than disabling the sandbox entirely (E11 §4): it specifically targets
the E32 abstraction, leaving room to later re-enable a *different* backend
kind once the incident is understood, without ever falling back to "no
isolation" as a side effect.

## 2. Reconstruct the run's isolation history

Every environment decision for a run is durably recorded — this is what
gate criterion (10) (`docs/v2_platform/beta_gap_analysis.md` §11) means by
"proven by run records, not by configuration":

```python
from backend.environments.manager import EnvironmentManager

manager = EnvironmentManager(...)
manager.list_for_run(run_id)             # EnvironmentRecord: backend kind, profile, lifecycle timestamps
manager.list_decisions_for_run(run_id)   # every allow/deny policy decision, with reason
```

Or via the event store directly — filter the run's events
(`GET /v2/flows/runs/{run_id}/events`, or `python -m backend.persistence.backup verify`
for an offline export) for:

- `environment.instance.provisioned` — backend kind and profile actually used
- `environment.access.allowed` / `environment.access.denied` — every
  network/filesystem decision, with `reason`
- `environment.instance.retired` — confirms clean teardown, or its absence
  flags an orphaned instance

## 3. Check for orphaned instances

`AUTODEV_ENVIRONMENT_TTL_SECONDS` (default 1800s) governs TTL-based reaping
of orphaned environments; `AUTODEV_ENVIRONMENT_MAX_CONCURRENT` (default 8)
is the per-tenant concurrency ceiling. If the incident involved a run that
never reached `environment.instance.retired`:

1. Confirm the reaper is actually running (it is part of the orchestrator's
   normal cycle, not a separate process) — a stuck orphan past the TTL with
   no retirement event is itself worth escalating, not just cleaning up.
2. Fall back to §4's container-level containment
   (`docker ps --filter ancestor=...`, preserve before removing) for the
   underlying process, since the E32 abstraction's own teardown path is
   exactly what's suspected of having failed.

## 4. Confirm containment

Re-run the E32 policy contract tests against the restarted backend as a
sanity check (not a substitute for manual review of what actually
happened):

```bash
.venv/bin/python -m pytest backend/tests/unit/environments/test_policy.py \
  backend/tests/unit/environments/test_manager.py -q
```

## 5. Root cause and follow-up

- If the root cause is a genuine gap in the hardened-container backend's
  isolation strength (not a misconfiguration), this is exactly the case
  E28 (v2.2, microVM-class isolation) exists to close — file the finding
  against E28, do not attempt to build a stronger backend inline during
  incident response.
- If the root cause is a misconfigured network/filesystem policy (an
  allowlist too broad for the workload), fix the `EnvironmentProfile`
  declaration and add a regression test to
  `backend/tests/unit/environments/test_policy.py` before reverting
  `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND`.
- Preserve evidence per `e11_incident_response.md` §6 before any cleanup.
