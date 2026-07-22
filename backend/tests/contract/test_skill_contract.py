"""Contract test for the ``skill`` extension point (E12-S2).

Asserts two independent guarantees:

* The :class:`~backend.skills.base.Skill` structural Protocol shape (and its
  :class:`~backend.skills.base.BaseSkill` ABC) is stable.
* :func:`~backend.skills.manifest.validate_manifest` round-trips a minimal
  valid ``skill.yaml`` document and rejects an invalid one.
"""

from __future__ import annotations

from backend.skills.base import BaseSkill, Skill, SkillContext, SkillResult
from backend.skills.manifest import SkillManifest, validate_manifest

VALID_RAW: dict[str, object] = {
    "schemaVersion": "1",
    "id": "autodev/skill-contract-probe",
    "version": "1.0.0",
    "name": "Contract Probe",
    "description": "Minimal deterministic skill used by the contract test.",
    "hostApi": ">=2.0,<3.0",
    "kind": "deterministic",
    "entrypoint": "autodev_skills.probe:run",
    "io": {
        "input": {
            "schemaVersion": "1",
            "type": "object",
            "required": ["repoRef"],
            "properties": {"repoRef": {"type": "string"}},
        },
        "output": {
            "schemaVersion": "1",
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        },
    },
    "permissions": {"filesystem": "read", "network": "none", "sandbox": True},
}


class _EchoSkill(BaseSkill):
    """Minimal :class:`BaseSkill` implementation used to prove the ABC shape."""

    name = "echo"
    description = "Echoes its input back as content."

    def run(self, context: SkillContext) -> SkillResult:
        """Echo the input mapping back as the result content.

        Args:
            context: The invocation context.

        Returns:
            A :class:`SkillResult` echoing ``context.inputs``.
        """
        return SkillResult(content=str(context.inputs), data=dict(context.inputs))


def test_skill_protocol_shape_is_stable() -> None:
    """A BaseSkill subclass satisfies the documented Skill structural shape.

    ``Skill`` (backend.skills.base) is a plain, non-``Protocol`` class used
    purely as documentation of the required shape (``name``, ``description``,
    ``run(context) -> SkillResult``); it is intentionally not used as a
    static type annotation here since ``BaseSkill`` does not inherit from
    it. The shape itself -- attribute names and the ``run`` signature -- is
    what this test pins.
    """
    skill = _EchoSkill()

    assert "name" in Skill.__annotations__
    assert "description" in Skill.__annotations__
    assert callable(Skill.run)
    assert isinstance(skill.name, str)
    assert isinstance(skill.description, str)
    result = skill.run(SkillContext(inputs={"x": 1}))

    assert isinstance(result, SkillResult)
    assert result.success is True


def test_skill_manifest_round_trips_a_minimal_valid_document() -> None:
    """A minimal valid skill.yaml document parses into a typed SkillManifest."""
    result = validate_manifest(VALID_RAW)

    assert result.valid is True
    assert result.errors == []
    assert isinstance(result.manifest, SkillManifest)
    assert result.manifest.id == "autodev/skill-contract-probe"
    assert result.manifest.kind == "deterministic"


def test_skill_manifest_rejects_an_invalid_document() -> None:
    """A skill.yaml document with a bad SemVer version is rejected."""
    raw = dict(VALID_RAW)
    raw["version"] = "not-a-version"

    result = validate_manifest(raw)

    assert result.valid is False
    assert any("SemVer" in error for error in result.errors)
    assert result.manifest is None
