"""Tests for exact-value secret redaction (E33-S2-T2/T3)."""

from __future__ import annotations

import pytest

from backend.secret_store.contracts import SecretReference
from backend.secret_store.redaction import (
    REDACTED_MARKER,
    SecretRedactor,
    redact_event_data,
    register_live_secret_value,
    reset_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _ref(name: str = "git-token") -> SecretReference:
    return SecretReference(tenant_id="t1", project="default", name=name)


def test_scrub_replaces_known_value() -> None:
    redactor = SecretRedactor({"s3cr3t-value": _ref()})
    assert redactor.scrub("token=s3cr3t-value end") == f"token={REDACTED_MARKER} end"


def test_scrub_leaves_unknown_text_untouched() -> None:
    redactor = SecretRedactor({"s3cr3t-value": _ref()})
    assert redactor.scrub("nothing secret here") == "nothing secret here"


def test_find_leaks_reports_the_reference_and_location() -> None:
    redactor = SecretRedactor({"s3cr3t-value": _ref("git-token")})
    leaks = redactor.find_leaks("echo s3cr3t-value", location="run-1/action-1.log")
    assert len(leaks) == 1
    assert leaks[0].reference.name == "git-token"
    assert leaks[0].location == "run-1/action-1.log"


def test_find_leaks_empty_when_no_match() -> None:
    redactor = SecretRedactor({"s3cr3t-value": _ref()})
    assert redactor.find_leaks("clean output", location="x") == []


def test_redact_event_data_scrubs_registered_values_recursively() -> None:
    register_live_secret_value("s3cr3t-value")
    data = {"message": "using s3cr3t-value now", "nested": {"list": ["a", "s3cr3t-value"]}}
    redacted = redact_event_data(data)
    assert redacted["message"] == f"using {REDACTED_MARKER} now"
    assert redacted["nested"]["list"] == ["a", REDACTED_MARKER]


def test_redact_event_data_is_a_noop_with_no_registered_values() -> None:
    data = {"message": "hello"}
    assert redact_event_data(data) == data


def test_blank_value_is_never_registered() -> None:
    register_live_secret_value("")
    data = {"message": ""}
    # Would corrupt every empty-string field if the empty string were
    # treated as a "known secret value" -- must be a no-op.
    assert redact_event_data(data) == data
