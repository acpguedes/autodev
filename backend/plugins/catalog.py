"""Canonical v2 plugin extension-point catalog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExtensionPointKind(StrEnum):
    AGENT = "agent"
    SKILL = "skill"
    TOOL = "tool"
    REASONING = "reasoning"
    ROUTER = "router"
    SELECTOR = "selector"
    EVALUATOR = "evaluator"
    CONTEXT_PROVIDER = "context_provider"
    RETRIEVER = "retriever"
    VALIDATION_GATE = "validation_gate"
    UI_PANEL = "ui_panel"
    EVENT_HANDLER = "event_handler"


@dataclass(frozen=True)
class ExtensionPoint:
    kind: ExtensionPointKind
    host_subsystem: str
    provides: str
    related_epic: str
    contract_version: str = "1.0.0"


EXTENSION_POINTS: dict[ExtensionPointKind, ExtensionPoint] = {
    ExtensionPointKind.AGENT: ExtensionPoint(
        ExtensionPointKind.AGENT,
        "Agent Runtime + Agent Registry",
        "Autonomous agent unit with capabilities, IO schema, policy, and budgets",
        "E2",
    ),
    ExtensionPointKind.SKILL: ExtensionPoint(
        ExtensionPointKind.SKILL,
        "Skill Registry",
        "Reusable deterministic or LLM-assisted function",
        "E6",
    ),
    ExtensionPointKind.TOOL: ExtensionPoint(
        ExtensionPointKind.TOOL,
        "Agent Runtime",
        "Low-level callable exposed to agents",
        "E2",
    ),
    ExtensionPointKind.REASONING: ExtensionPoint(
        ExtensionPointKind.REASONING,
        "Reasoning Engine",
        "Pluggable reasoning strategy",
        "E4",
    ),
    ExtensionPointKind.ROUTER: ExtensionPoint(
        ExtensionPointKind.ROUTER,
        "Router & Selector",
        "Intent classification",
        "E5",
    ),
    ExtensionPointKind.SELECTOR: ExtensionPoint(
        ExtensionPointKind.SELECTOR,
        "Router & Selector",
        "Agent/model/strategy selection",
        "E5",
    ),
    ExtensionPointKind.EVALUATOR: ExtensionPoint(
        ExtensionPointKind.EVALUATOR,
        "Evaluation Service",
        "Output or decision scoring",
        "E5/E12",
    ),
    ExtensionPointKind.CONTEXT_PROVIDER: ExtensionPoint(
        ExtensionPointKind.CONTEXT_PROVIDER,
        "Context/RAG Service",
        "Context source for files, symbols, memory, or external systems",
        "E7",
    ),
    ExtensionPointKind.RETRIEVER: ExtensionPoint(
        ExtensionPointKind.RETRIEVER,
        "Context/RAG Service",
        "Lexical or vector retrieval",
        "E7",
    ),
    ExtensionPointKind.VALIDATION_GATE: ExtensionPoint(
        ExtensionPointKind.VALIDATION_GATE,
        "Execution Sandbox + Orchestration Engine",
        "Quality gate executed in sandbox",
        "E3/E12",
    ),
    ExtensionPointKind.UI_PANEL: ExtensionPoint(
        ExtensionPointKind.UI_PANEL,
        "Web UI",
        "Panel, route, or widget mounted into a declared UI slot",
        "E10",
    ),
    ExtensionPointKind.EVENT_HANDLER: ExtensionPoint(
        ExtensionPointKind.EVENT_HANDLER,
        "Event Bus",
        "Asynchronous reaction to domain.entity.action events",
        "E9",
    ),
}

EXTENSION_POINT_KINDS = tuple(point.value for point in ExtensionPointKind)


def get_extension_point(kind: ExtensionPointKind | str) -> ExtensionPoint:
    normalized = ExtensionPointKind(kind)
    return EXTENSION_POINTS[normalized]


__all__ = [
    "EXTENSION_POINT_KINDS",
    "EXTENSION_POINTS",
    "ExtensionPoint",
    "ExtensionPointKind",
    "get_extension_point",
]
