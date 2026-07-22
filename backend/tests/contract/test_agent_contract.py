"""Contract test for the ``agent`` extension point (E12-S2).

Asserts two independent guarantees:

* The :class:`~backend.agents.base.Agent` structural Protocol shape is
  stable -- a minimal conforming object satisfies it.
* :func:`~backend.agents.manifest.validate_agent_manifest` round-trips a
  minimal valid ``agent.yaml`` document and rejects an invalid one.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agents.base import Agent, AgentContext, AgentResult
from backend.agents.manifest import AgentManifest, validate_agent_manifest


def _input_schema() -> dict[str, object]:
    """Build a minimal JSON Schema for the contract fixture's agent input."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "task"],
        "properties": {
            "schemaVersion": {"const": "1.0.0"},
            "task": {"type": "string", "minLength": 1},
        },
    }


def _output_schema() -> dict[str, object]:
    """Build a minimal JSON Schema for the contract fixture's agent output."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "status", "result"],
        "properties": {
            "schemaVersion": {"const": "1.0.0"},
            "status": {"enum": ["ok", "error"]},
            "result": {"type": "string"},
        },
    }


def _valid_agent_manifest() -> dict[str, object]:
    """Build a minimal, fully valid raw ``agent.yaml`` document."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/agent-contract-probe",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [
            {"id": "code.implementation", "version": "1.0.0", "level": "primary"},
        ],
        "io": {
            "contract": "acme/contract-probe-io",
            "contractVersion": "1.0.0",
            "input": _input_schema(),
            "output": _output_schema(),
            "onInvalidOutput": "fail",
        },
        "permissions": {"tools": [], "skills": []},
        "entrypoint": {"runtime": "python", "ref": "acme_probe.agent:ProbeAgent"},
    }


@dataclass(slots=True)
class _EchoAgent:
    """Minimal object satisfying the :class:`Agent` structural Protocol."""

    name: str = "echo"

    def run(self, context: AgentContext) -> AgentResult:
        """Echo the incoming goal back as the result content.

        Args:
            context: The invocation context.

        Returns:
            An :class:`AgentResult` echoing ``context.goal``.
        """
        return AgentResult(content=context.goal or "")


def test_agent_protocol_shape_is_stable() -> None:
    """A minimal conforming object satisfies the Agent structural Protocol."""
    agent: Agent = _EchoAgent()

    assert isinstance(agent.name, str)
    result = agent.run(AgentContext(session_id="s1", goal="hello"))

    assert isinstance(result, AgentResult)
    assert result.content == "hello"


def test_agent_manifest_round_trips_a_minimal_valid_document() -> None:
    """A minimal valid agent.yaml document parses into a typed AgentManifest."""
    result = validate_agent_manifest(_valid_agent_manifest())

    assert result.valid is True
    assert result.errors == []
    assert isinstance(result.manifest, AgentManifest)
    assert result.manifest.id == "acme/agent-contract-probe"
    assert result.manifest.host_api == ">=2.0 <3.0"


def test_agent_manifest_rejects_an_invalid_document() -> None:
    """An invalid agent.yaml document (bad id, unknown capability) is rejected."""
    raw = _valid_agent_manifest()
    raw["id"] = "Bad/Agent"
    raw["capabilities"] = [{"id": "magic.do-anything", "version": "1.0.0"}]

    result = validate_agent_manifest(raw)

    assert result.valid is False
    assert "id must use namespace/name kebab-case format" in result.errors
    assert "unknown capability magic.do-anything" in result.errors
    assert result.manifest is None
