"""Versioned capability vocabulary for v2 agent manifests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    version: str
    description: str


CAPABILITY_VOCABULARY: dict[str, CapabilityDefinition] = {
    "code.implementation": CapabilityDefinition(
        "code.implementation",
        "1.0.0",
        "Implement source changes and produce patch-oriented work output.",
    ),
    "code.refactor": CapabilityDefinition(
        "code.refactor",
        "1.0.0",
        "Restructure existing code without changing intended behavior.",
    ),
    "planning.decompose": CapabilityDefinition(
        "planning.decompose",
        "1.0.0",
        "Break a user goal into ordered engineering steps.",
    ),
    "security.review": CapabilityDefinition(
        "security.review",
        "1.0.0",
        "Inspect changes for security risks and policy violations.",
    ),
    "validation.plan": CapabilityDefinition(
        "validation.plan",
        "1.0.0",
        "Produce concrete validation steps and success criteria.",
    ),
}

CAPABILITY_IDS = frozenset(CAPABILITY_VOCABULARY)


__all__ = ["CAPABILITY_IDS", "CAPABILITY_VOCABULARY", "CapabilityDefinition"]
