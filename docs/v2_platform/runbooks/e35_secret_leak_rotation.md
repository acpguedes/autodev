# Secret Rotation Under Suspected Leak — Runbook (E35-S3)

Trigger: a `secret.leak.suspected` audit event fires (a task echoed a
secret's exact value into collected evidence, caught by the process-wide
redaction registry, `backend/secret_store/redaction.py`), or any external
report that a secret referenced by AutoDev may have been exposed.

`secret.leak.suspected` firing is itself **evidence the redaction worked**
— the value never reached persisted evidence in cleartext (gate criterion
(11), `docs/v2_platform/beta_gap_analysis.md` §11). It does not mean the
value is safe going forward: the value existed in the live secret store and
was materialized into at least one execution environment, so it must be
treated as compromised.

## 1. Immediate: rotate, don't just revoke

Rotating (not only revoking) is the first action, because revoking alone
does not invalidate the *external* credential the secret's value
represents — only the AutoDev-side reference stops resolving. Rotate
first, then separately invalidate the old credential at its source system
(this runbook cannot do that step for you — it is specific to whatever the
secret authenticates to).

```bash
# New value read from stdin only — never a CLI argument (E33-S1 contract)
echo -n "$NEW_VALUE" | autodev secrets rotate <tenant_id> <name> --project <project> --value-stdin
```

Effect (per `docs/execution/upgrade.md`-adjacent contract in
`docs/security/secrets.md`): rotation takes effect on the very next
`EnvironmentManager.provision()` / `bind_environment()` call — nothing
caches a resolved value across provisions, so there is no propagation delay
to reason about. Any environment already provisioned before the rotation
keeps the old value for its remaining lifetime; if the suspected leak is
active *right now*, also force environment provisioning closed
(`docs/v2_platform/runbooks/e35_isolation_violation_incident.md` §1) until
you have confirmed no in-flight environment still holds the old value.

## 2. If rotation isn't enough: revoke

Revoke when the secret must stop being usable entirely (not just get a new
value) — e.g. the reference itself should no longer exist for this
tenant/project:

```bash
autodev secrets revoke <tenant_id> <name> --project <project>
```

Effect: **fails closed** for every future direct resolution
(`SecretStore.resolve()` raises `SecretRevokedError` — see
`backend/secret_store/contracts.py`); at the environment-injection
boundary specifically, a revoked reference is **skipped** rather than
failing the whole environment (`backend/environments/manager.py`,
E33-S3) — the environment still provisions, just without that secret in
its env. Confirm which behavior you expect for the affected workload
before relying on "revoke" alone to stop a task that depends on the secret
being present.

## 3. Confirm no cleartext value persisted

1. Query for the triggering `secret.leak.suspected` event and inspect its
   payload — it should describe *that* a leak was caught, never the value
   itself (the redactor scrubs before the event is emitted, inside
   `emit_event()` itself — every producer is protected, not just
   environment events).
2. Spot-check any artifact/log/diff the flagged task produced
   (`backend/artifacts/`) for the *redacted* placeholder rather than the
   real value — if the real value is found anywhere in persisted evidence,
   that is a redaction-contract failure, escalate it separately from the
   leak itself (file against `backend/secret_store/redaction.py`, not this
   runbook).
3. `docs/security/secrets.md` states the scope reduction honestly: exact-
   value redaction is guaranteed; entropy-based detection of an
   *unregistered* secret-shaped string is not attempted. If the "leak" was
   actually an unregistered credential (never went through
   `autodev secrets create`), redaction would not have caught it — treat
   this as a process gap (the credential should have been a managed
   secret) rather than a redaction bug.

## 4. Audit trail for the incident report

```bash
autodev secrets list <tenant_id> --project <project>   # current metadata (never values)
curl -s "$BASE_URL/v2/audit/access?limit=200" -o access-audit.json
```

Cross-reference `secret.created` / `.rotated` / `.revoked` / `.resolved` /
`.leak.suspected` event timestamps (catalog:
`backend/events/catalog.py`) against the access-audit trail to reconstruct
who/what resolved the secret before and after rotation.

## 5. Follow-up

- If the leak fixture (a task echoing a secret) is reproducible, add it as
  a regression case alongside the existing coverage in
  `backend/tests/unit/secret_store/test_service.py`.
- If rotation cadence needs to be automatic rather than incident-triggered,
  that is out of this runbook's scope — E33 delivered manual rotation via
  CLI/API only; a scheduled-rotation policy would be its own story.
