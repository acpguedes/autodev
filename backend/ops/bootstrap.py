"""Self-host bootstrap (E34-S2-T1).

``autodev bootstrap`` brings a self-hosted deployment to a usable state:
preflight diagnostics (:mod:`backend.ops.doctor`) first, then state-store
initialization — schema migrations run as a side effect of constructing the
configured store (``backend.persistence.sqlite_adapter.SQLiteStore`` /
``backend.persistence.postgres_adapter.PostgresStore``). Safe to re-run:
every step it performs is itself idempotent (diagnostics are read-only,
migrations only apply what is not yet applied).

Secrets are never bootstrapped inline — nothing here accepts or writes a
plaintext secret value. A deployment that needs secrets available at
bootstrap time creates them out-of-band via ``autodev secrets create``
(E33-S1, value read from stdin only) and references them by name; this
command does not manage secret material at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.ops.doctor import DiagnosticCheck, diagnostics_ok, run_diagnostics

BootstrapStatus = Literal["ok", "fail"]


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of a bootstrap attempt.

    Attributes:
        status: ``"ok"`` if bootstrap completed, ``"fail"`` if preflight
            diagnostics blocked it before any state was touched.
        checks: The preflight diagnostics that were run.
        profile: Active ``AUTODEV_PROFILE`` at bootstrap time (empty when
            preflight failed, since settings may not have loaded).
        storage_backend: Active artifact storage posture (empty when
            preflight failed).
    """

    status: BootstrapStatus
    checks: tuple[DiagnosticCheck, ...]
    profile: str = ""
    storage_backend: str = ""

    def as_dict(self) -> dict[str, object]:
        """Return this result as a JSON-serializable dict."""
        payload: dict[str, object] = {
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
        }
        if self.status == "ok":
            payload["profile"] = self.profile
            payload["storage_backend"] = self.storage_backend
        return payload


def bootstrap() -> BootstrapResult:
    """Run preflight diagnostics, then initialize the configured state store.

    Fails closed: if any preflight check fails, no store is touched and the
    failing checks are returned for a typed, actionable report.

    Returns:
        The bootstrap outcome.
    """
    checks = run_diagnostics()
    if not diagnostics_ok(checks):
        return BootstrapResult(status="fail", checks=checks)

    from backend.config.settings import get_settings
    from backend.persistence.database import get_store, reset_store_cache

    settings = get_settings()
    reset_store_cache()
    get_store()  # constructing the store applies any pending migrations

    return BootstrapResult(
        status="ok",
        checks=checks,
        profile=settings.autodev_profile,
        storage_backend=settings.storage_backend,
    )


__all__ = ["BootstrapResult", "BootstrapStatus", "bootstrap"]
