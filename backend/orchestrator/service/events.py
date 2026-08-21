"""Single indirection point for ``emit_event`` within this package (E47-S5).

Every mixin module calls ``events.emit_event(...)`` (module-qualified,
looked up at call time) rather than binding ``emit_event`` into its own
namespace with ``from backend.events.runtime import emit_event``. That keeps
one monkeypatchable choke point --
``backend.orchestrator.service.events.emit_event`` -- reaching every call
site across the package, the same property a single-file module gets for
free from sharing one namespace.
"""

from __future__ import annotations

from backend.events.runtime import emit_event

__all__ = ["emit_event"]
