"""Tests for the U2 skills subsystem.

Covers:
* discover_skills() returns the 3 built-ins.
* Each built-in produces expected deterministic output.
* invoke_skill raises KeyError on unknown name.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_skills_returns_three_builtins() -> None:
    from backend.skills import discover_skills

    skills = discover_skills()
    assert "summarize_diff" in skills
    assert "extract_symbols_lexical" in skills
    assert "render_checklist" in skills


def test_discover_skills_returns_skill_instances() -> None:
    from backend.skills import discover_skills

    skills = discover_skills()
    for name, skill in skills.items():
        assert hasattr(skill, "run"), f"Skill {name!r} has no run() method"
        assert callable(skill.run), f"Skill {name!r}.run is not callable"


# ---------------------------------------------------------------------------
# summarize_diff
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
--- a/backend/agents/base.py
+++ b/backend/agents/base.py
@@ -1,4 +1,6 @@
 # unchanged line
+added line one
+added line two
-removed line
 # another unchanged
--- a/backend/cli.py
+++ b/backend/cli.py
@@ -10,3 +10,4 @@
 existing line
+new cli line
"""


def test_summarize_diff_counts_lines() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={"diff": SAMPLE_DIFF})
    result = invoke_skill("summarize_diff", ctx)

    assert result.success is True
    assert result.data["added_lines"] == 3
    assert result.data["removed_lines"] == 1
    assert result.data["changed_file_count"] == 2
    assert "backend/agents/base.py" in result.data["changed_files"]
    assert "backend/cli.py" in result.data["changed_files"]


def test_summarize_diff_empty_input() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={"diff": ""})
    result = invoke_skill("summarize_diff", ctx)

    assert result.success is True
    assert result.data["added_lines"] == 0
    assert result.data["removed_lines"] == 0
    assert result.data["changed_file_count"] == 0


# ---------------------------------------------------------------------------
# extract_symbols_lexical
# ---------------------------------------------------------------------------

SAMPLE_PYTHON = """\
class Foo:
    def method(self):
        pass

def bar():
    pass

class _Private:
    pass

def baz():
    pass
"""


def test_extract_symbols_python() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={"code": SAMPLE_PYTHON, "language": "python"})
    result = invoke_skill("extract_symbols_lexical", ctx)

    assert result.success is True
    symbols = result.data["symbols"]
    assert "Foo" in symbols
    assert "bar" in symbols
    assert "_Private" in symbols
    assert "baz" in symbols
    # Inner method should not appear (not top-level column 0)
    assert "method" not in symbols


def test_extract_symbols_empty_code() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={"code": "", "language": "python"})
    result = invoke_skill("extract_symbols_lexical", ctx)

    assert result.success is True
    assert result.data["symbols"] == []


# ---------------------------------------------------------------------------
# render_checklist
# ---------------------------------------------------------------------------


def test_render_checklist_produces_markdown() -> None:
    from backend.skills import SkillContext, invoke_skill

    items = ["Write tests", "Run linter", "Deploy"]
    ctx = SkillContext(inputs={"items": items})
    result = invoke_skill("render_checklist", ctx)

    assert result.success is True
    lines = result.content.splitlines()
    assert len(lines) == 3
    for line in lines:
        assert line.startswith("- [ ] ")
    assert "Write tests" in result.content
    assert result.data["item_count"] == 3


def test_render_checklist_empty_list() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={"items": []})
    result = invoke_skill("render_checklist", ctx)

    assert result.success is True
    assert result.content == "(empty checklist)"
    assert result.data["item_count"] == 0


# ---------------------------------------------------------------------------
# invoke_skill error handling
# ---------------------------------------------------------------------------


def test_invoke_skill_raises_on_unknown_name() -> None:
    from backend.skills import SkillContext, invoke_skill

    ctx = SkillContext(inputs={})
    with pytest.raises(KeyError, match="no_such_skill"):
        invoke_skill("no_such_skill", ctx)


# ---------------------------------------------------------------------------
# register_skill decorator
# ---------------------------------------------------------------------------


def test_register_skill_decorator_returns_class_unchanged() -> None:
    from backend.skills import registry as reg

    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    try:
        from backend.skills import SkillContext, SkillResult, register_skill

        @register_skill("test-skill")
        class _TestSkill:
            name = "test-skill"
            description = "A test skill."

            def run(self, context: SkillContext) -> SkillResult:
                return SkillResult(content="ok")

        # Class is unchanged (still a class, not the instance)
        assert isinstance(_TestSkill, type)
        # But an instance is registered
        assert "test-skill" in reg._REGISTRY
        instance = reg._REGISTRY["test-skill"]
        assert hasattr(instance, "run")
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(original)
