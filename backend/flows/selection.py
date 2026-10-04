"""Two-phase flow selection (E63-S3).

Phase one is a **deterministic gate**: every flow whose ``requires``
preconditions conflict with the probed project state is eliminated before any
model sees it. Phase two is a **constrained choice** among the survivors, with
``"none"`` a first-class answer. The gate -- not the model -- is what
enforces applicability; any chooser error, timeout or unparseable answer
fails closed to "no flow".

Only flow metadata and the task text reach the chooser: never project file
contents, secrets, or the project root path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any, Callable, Literal, Sequence

from backend.events.runtime import emit_event
from backend.flows.model import FlowManifest, FlowRequires
from backend.projects.state import ProjectState

logger = logging.getLogger(__name__)

#: A chooser receives the task text and candidate metadata documents and
#: returns ``{"flow": "<id>|none", "input": {...}}`` (or a JSON string of it).
Chooser = Callable[[str, Sequence[dict[str, Any]]], Any]


@dataclass(frozen=True)
class FlowSelection:
    """The recorded outcome of one selection.

    Attributes:
        outcome: ``matched`` (run ``flow_id``), ``skipped`` (run directly) or
            ``question`` (ask the user for one missing input first).
        flow_id: The chosen flow id, when ``matched`` or ``question``.
        version: The chosen flow version, when ``matched`` or ``question``.
        input: Run input extracted by the chooser for the chosen flow.
        candidates: Flow ids that survived the deterministic gate.
        eliminated: ``{"flowId", "rule"}`` for every gate elimination.
        reason: Human-readable reason for the outcome.
        question: The single targeted question, when ``outcome == "question"``.
    """

    outcome: Literal["matched", "skipped", "question"]
    flow_id: str = ""
    version: str = ""
    input: dict[str, Any] | None = None
    candidates: tuple[str, ...] = ()
    eliminated: tuple[dict[str, str], ...] = ()
    reason: str = ""
    question: str = ""


def requires_conflict(requires: FlowRequires | None, state: ProjectState) -> str:
    """Return the first precondition *state* violates, or ``""`` when none.

    Args:
        requires: A flow's declared preconditions (``None`` means none).
        state: The probed project state.

    Returns:
        A rule description such as ``"requires.populated=False"``, or ``""``.
    """
    if requires is None:
        return ""
    for name in ("populated", "git", "tests"):
        wanted = getattr(requires, name)
        if wanted is not None and wanted != getattr(state, name):
            return f"requires.{name}={wanted}"
    if requires.languages and not set(requires.languages) & set(state.languages):
        return f"requires.languages={list(requires.languages)}"
    return ""


def _metadata(manifest: FlowManifest) -> dict[str, Any]:
    """Model-visible metadata for one candidate (no project data)."""
    schema = manifest.input.schema if manifest.input else {}
    return {
        "id": manifest.id,
        "purpose": manifest.purpose,
        "whenToUse": manifest.when_to_use,
        "whenNotToUse": manifest.when_not_to_use,
        "input": schema,
    }


def _parse_choice(raw: Any) -> dict[str, Any] | None:
    """Parse a chooser answer into ``{"flow", "input"}``; ``None`` if invalid."""
    if isinstance(raw, str):
        text = raw.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            raw = json.loads(match.group(0))
        except ValueError:
            return None
    if not isinstance(raw, dict) or not isinstance(raw.get("flow"), str):
        return None
    flow_input = raw.get("input")
    return {
        "flow": raw["flow"].strip(),
        "input": flow_input if isinstance(flow_input, dict) else {},
    }


def llm_chooser(task: str, candidates: Sequence[dict[str, Any]]) -> Any:
    """Default chooser backed by the configured chat model.

    Returns ``"none"`` when no real provider is configured.

    Args:
        task: The user's task text.
        candidates: Candidate metadata documents.

    Returns:
        The raw model answer (parsed by the selector).
    """
    from backend.llm.factory import get_chat_model, is_configured_model  # noqa: PLC0415

    model = get_chat_model(max_tokens=300, request_timeout=20.0)
    if not is_configured_model(model):
        return {"flow": "none", "input": {}}
    prompt = (
        "Pick the single flow that fits the task, or none. Answer ONLY with JSON "
        '{"flow": "<id or none>", "input": {<values for the flow input '
        "properties that the task states>}}. Choose none unless a flow clearly "
        "fits.\n\nTask: "
        + task
        + "\n\nFlows:\n"
        + json.dumps(list(candidates), indent=1)
    )
    answer = model.invoke(prompt)
    return getattr(answer, "content", answer)


class FlowSelector:
    """Selects the flow (if any) that applies to a task in a project state."""

    def __init__(self, registry: Any, chooser: Chooser | None = None) -> None:
        """Initialize the selector.

        Args:
            registry: A :class:`~backend.flows.registry.FlowRegistry`.
            chooser: Phase-two chooser; defaults to :func:`llm_chooser`.
        """
        self._registry = registry
        self._chooser = chooser or llm_chooser

    def select(self, task: str, state: ProjectState) -> FlowSelection:
        """Select a flow for *task* given the probed project *state*.

        Args:
            task: The user's task text.
            state: The probed project state.

        Returns:
            The selection outcome; never raises.
        """
        try:
            return self._select(task, state)
        except Exception as exc:  # noqa: BLE001 - fail closed to "no flow"
            logger.warning("flow selection failed closed: %s", exc)
            return FlowSelection(outcome="skipped", reason=f"selection error: {exc}")

    def _select(self, task: str, state: ProjectState) -> FlowSelection:
        latest: dict[str, FlowManifest] = {}
        for manifest in self._registry.list_flows():
            known = latest.get(manifest.id)
            if known is None or _newer(manifest.version, known.version):
                latest[manifest.id] = manifest
        survivors: list[FlowManifest] = []
        eliminated: list[dict[str, str]] = []
        for manifest in latest.values():
            if not manifest.auto_selectable:
                continue
            rule = requires_conflict(manifest.requires, state)
            if rule:
                eliminated.append({"flowId": manifest.id, "rule": rule})
            else:
                survivors.append(manifest)
        candidates = tuple(m.id for m in survivors)
        gate = tuple(eliminated)
        if not survivors:
            return FlowSelection(
                outcome="skipped",
                eliminated=gate,
                reason="no flow is applicable to the project state",
            )
        try:
            choice = _parse_choice(self._chooser(task, [_metadata(m) for m in survivors]))
        except Exception as exc:  # noqa: BLE001 - provider error/timeout
            logger.warning("flow chooser failed: %s", exc)
            return FlowSelection(
                outcome="skipped",
                candidates=candidates,
                eliminated=gate,
                reason=f"chooser error: {exc}",
            )
        if choice is None:
            return FlowSelection(
                outcome="skipped",
                candidates=candidates,
                eliminated=gate,
                reason="unparseable chooser answer",
            )
        chosen = next((m for m in survivors if m.id == choice["flow"]), None)
        if chosen is None:
            reason = (
                "chooser answered none"
                if choice["flow"].lower() == "none"
                else "chooser named a flow outside the candidates"
            )
            return FlowSelection(
                outcome="skipped", candidates=candidates, eliminated=gate, reason=reason
            )
        missing = _missing_required(chosen, choice["input"])
        common: dict[str, Any] = {
            "flow_id": chosen.id,
            "version": chosen.version,
            "input": choice["input"],
            "candidates": candidates,
            "eliminated": gate,
        }
        if missing:
            return FlowSelection(
                outcome="question",
                reason=f"missing required input {missing!r}",
                question=f"To run {chosen.name or chosen.id}, what is the {missing}?",
                **common,
            )
        return FlowSelection(
            outcome="matched", reason=chosen.purpose or "chooser matched", **common
        )


def _newer(candidate: str, known: str) -> bool:
    """Whether SemVer *candidate* is newer than *known*."""
    from packaging.version import Version  # noqa: PLC0415

    return Version(candidate) > Version(known)


def _missing_required(manifest: FlowManifest, supplied: dict[str, Any]) -> str:
    """Return the first required input property not supplied, or ``""``."""
    schema = manifest.input.schema if manifest.input else {}
    for name in schema.get("required", []) or []:
        if supplied.get(name) in (None, ""):
            return str(name)
    return ""


def record_selection(
    selection: FlowSelection, *, tenant_id: str, run_id: str, session_id: str
) -> None:
    """Durably record a selection as a ``flow.selection.*`` event.

    Args:
        selection: The outcome to record.
        tenant_id: Tenant owning the run.
        run_id: Run the decision belongs to (the event partition).
        session_id: Session the run belongs to.
    """
    subject = {"runId": run_id, "sessionId": session_id}
    if selection.outcome == "matched":
        emit_event(
            "flow.selection.matched",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={
                "flowId": selection.flow_id,
                "flowVersion": selection.version,
                "candidates": list(selection.candidates),
                "eliminated": list(selection.eliminated),
                "reason": selection.reason,
            },
            subject=subject,
        )
        return
    emit_event(
        "flow.selection.skipped",
        tenant_id=tenant_id,
        partition_key=run_id,
        data={
            "candidates": list(selection.candidates),
            "eliminated": list(selection.eliminated),
            "reason": selection.reason,
            "question": selection.question,
        },
        subject=subject,
    )


__all__ = [
    "FlowSelection",
    "FlowSelector",
    "llm_chooser",
    "record_selection",
    "requires_conflict",
]
