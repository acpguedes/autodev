"""Shared coverage registry for the extension-point contract test tier.

This module is the single source of truth for *which* test module owns the
contract for each :class:`~backend.plugins.catalog.ExtensionPointKind`. It
exists so that ``test_extension_point_coverage.py`` can assert, for every
kind declared in :data:`backend.plugins.catalog.EXTENSION_POINTS`, that a
registration is present here -- turning "someone added a new extension-point
kind but forgot a contract test" into a build failure instead of a silent
gap.

Two registration states are supported:

* :attr:`ContractCoverageStatus.COVERED` -- a contract test module exists
  and is imported by the coverage test to prove it is collectible.
* :attr:`ContractCoverageStatus.PENDING` -- the kind is declared in the
  catalog but has no dedicated Protocol/ABC or manifest format in the
  codebase yet, so there is nothing to assert a contract against. This is a
  deliberate, reviewed gap (not a silent one): the coverage test still
  requires an explicit registration with a rationale, so a genuinely new,
  unregistered kind still fails the build.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.plugins.catalog import ExtensionPointKind


class ContractCoverageStatus(Enum):
    """Whether an extension-point kind currently has a contract test."""

    COVERED = "covered"
    PENDING = "pending"


@dataclass(frozen=True)
class ContractCoverage:
    """Registration record for one extension-point kind's contract test.

    Attributes:
        status: Whether the kind is covered by a contract test today.
        test_module: Dotted import path of the module that owns the
            contract test, when ``status`` is
            :attr:`ContractCoverageStatus.COVERED`. ``None`` when pending.
        note: Human-readable rationale -- either a short pointer to what the
            contract test covers, or (for pending kinds) why no contract
            test exists yet and which epic is expected to introduce one.
    """

    status: ContractCoverageStatus
    test_module: str | None
    note: str


#: Registration of every :class:`ExtensionPointKind` against the contract
#: test module that owns it, or an explicit, reviewed "pending" rationale.
#: ``test_extension_point_coverage.py`` requires every member of
#: ``ExtensionPointKind`` to appear here, so adding a new kind to the
#: catalog without updating this map fails the build.
EXTENSION_POINT_CONTRACT_COVERAGE: dict[ExtensionPointKind, ContractCoverage] = {
    ExtensionPointKind.AGENT: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.contract.test_agent_contract",
        "Agent Protocol shape (backend.agents.base) and agent.yaml manifest "
        "round-trip (backend.agents.manifest).",
    ),
    ExtensionPointKind.SKILL: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.contract.test_skill_contract",
        "Skill/BaseSkill Protocol shape (backend.skills.base) and skill.yaml "
        "manifest round-trip (backend.skills.manifest).",
    ),
    ExtensionPointKind.TOOL: ContractCoverage(
        ContractCoverageStatus.PENDING,
        None,
        "No dedicated Tool Protocol or tool manifest format exists yet "
        "(tools are currently agent-scoped capabilities, see E2); add a "
        "contract test once a standalone Tool extension point ships.",
    ),
    ExtensionPointKind.REASONING: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.unit.reasoning.test_reasoning_contract",
        "Reuses the existing E4-S1 reasoning contract test "
        "(REASONING_CONTRACT_HOST_API, ReasoningEngine, strategy registry).",
    ),
    ExtensionPointKind.ROUTER: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.unit.routing.test_routing_contract",
        "Reuses the existing E5-S1/S2 routing contract test "
        "(RoutingPolicy, Router.route(), RoutingService trace events).",
    ),
    ExtensionPointKind.SELECTOR: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.unit.routing.test_routing_contract",
        "Selector is validated as part of RoutingPolicy in the same "
        "routing contract test (policy.selector); no separate module.",
    ),
    ExtensionPointKind.EVALUATOR: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.unit.evals.test_evals_contract",
        "Reuses the existing evaluator contract test "
        "(EVAL_CONTRACT_HOST_API and the evals contract surface).",
    ),
    ExtensionPointKind.CONTEXT_PROVIDER: ContractCoverage(
        ContractCoverageStatus.COVERED,
        "backend.tests.contract.test_context_provider_contract",
        "ContextProvider runtime-checkable Protocol shape "
        "(backend.context.provider) plus a conforming implementation.",
    ),
    ExtensionPointKind.RETRIEVER: ContractCoverage(
        ContractCoverageStatus.PENDING,
        None,
        "No dedicated Retriever Protocol exists yet as a standalone "
        "extension point (E7); add a contract test once it ships.",
    ),
    ExtensionPointKind.VALIDATION_GATE: ContractCoverage(
        ContractCoverageStatus.PENDING,
        None,
        "No dedicated ValidationGate Protocol/manifest exists yet as a "
        "standalone extension point (E3/E12); add a contract test once it "
        "ships.",
    ),
    ExtensionPointKind.UI_PANEL: ContractCoverage(
        ContractCoverageStatus.PENDING,
        None,
        "No dedicated UiPanel Protocol/manifest exists yet as a backend "
        "extension point (E10, Web UI); add a contract test once it ships.",
    ),
    ExtensionPointKind.EVENT_HANDLER: ContractCoverage(
        ContractCoverageStatus.PENDING,
        None,
        "No dedicated EventHandler Protocol/manifest exists yet as a "
        "standalone extension point (E9); add a contract test once it "
        "ships.",
    ),
}


__all__ = [
    "EXTENSION_POINT_CONTRACT_COVERAGE",
    "ContractCoverage",
    "ContractCoverageStatus",
]
