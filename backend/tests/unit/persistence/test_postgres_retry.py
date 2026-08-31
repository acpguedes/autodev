"""Unit tests for PostgreSQL transient-error classification and retry (E60-S3-T2/T3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.persistence.postgres_adapter import (
    PostgresDeadlockError,
    PostgresRetryConfig,
    PostgresSerializationFailureError,
    classify_postgres_error,
    pool_retry_config_from_settings,
    run_with_postgres_retry,
)


def _psycopg_error(sqlstate: str | None) -> Exception:
    """Build a fake psycopg-style error carrying ``diag.sqlstate``, like real driver errors."""
    exc = RuntimeError("boom")
    exc.diag = SimpleNamespace(sqlstate=sqlstate)  # type: ignore[attr-defined]
    return exc


def test_classify_postgres_error_detects_deadlock() -> None:
    """SQLSTATE 40P01 (deadlock_detected) classifies as a typed deadlock error."""
    classified = classify_postgres_error(_psycopg_error("40P01"))
    assert isinstance(classified, PostgresDeadlockError)


def test_classify_postgres_error_detects_serialization_failure() -> None:
    """SQLSTATE 40001 (serialization_failure) classifies as a typed serialization error."""
    classified = classify_postgres_error(_psycopg_error("40001"))
    assert isinstance(classified, PostgresSerializationFailureError)


def test_classify_postgres_error_ignores_unrelated_sqlstate() -> None:
    """A non-transient SQLSTATE (e.g. a unique-violation) is never classified as retryable."""
    assert classify_postgres_error(_psycopg_error("23505")) is None


def test_classify_postgres_error_ignores_errors_without_sqlstate() -> None:
    """A plain exception with no ``diag`` attribute is never classified as retryable."""
    assert classify_postgres_error(ValueError("not a database error")) is None


def test_run_with_postgres_retry_retries_deadlock_then_succeeds() -> None:
    """A deadlock victim on the first attempt is retried and the second attempt's result returned."""
    attempts = {"count": 0}
    sleeps: list[float] = []

    def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _psycopg_error("40P01")
        return "ok"

    result = run_with_postgres_retry(
        operation,
        config=PostgresRetryConfig(max_attempts=3, base_delay_seconds=0.01),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert sleeps == [0.01]


def test_run_with_postgres_retry_backs_off_exponentially() -> None:
    """Successive retries wait ``base * 2 ** attempt_index`` between attempts."""
    sleeps: list[float] = []

    def always_deadlocks() -> None:
        raise _psycopg_error("40P01")

    with pytest.raises(PostgresDeadlockError):
        run_with_postgres_retry(
            always_deadlocks,
            config=PostgresRetryConfig(max_attempts=4, base_delay_seconds=0.01),
            sleep=sleeps.append,
        )

    assert sleeps == [0.01, 0.02, 0.04]


def test_run_with_postgres_retry_exhausts_attempts_and_raises_typed_error() -> None:
    """Every attempt failing with a serialization failure raises the typed error, not the raw one."""
    with pytest.raises(PostgresSerializationFailureError):
        run_with_postgres_retry(
            lambda: (_ for _ in ()).throw(_psycopg_error("40001")),
            config=PostgresRetryConfig(max_attempts=2, base_delay_seconds=0.01),
            sleep=lambda _seconds: None,
        )


def test_run_with_postgres_retry_never_retries_non_transient_errors() -> None:
    """A non-retryable error propagates immediately, without consuming a retry attempt or sleeping."""
    attempts = {"count": 0}
    sleeps: list[float] = []

    def operation() -> None:
        attempts["count"] += 1
        raise _psycopg_error("23505")

    with pytest.raises(RuntimeError):
        run_with_postgres_retry(
            operation,
            config=PostgresRetryConfig(max_attempts=3, base_delay_seconds=0.01),
            sleep=sleeps.append,
        )

    assert attempts["count"] == 1
    assert sleeps == []


def test_postgres_retry_config_rejects_invalid_bounds() -> None:
    """Retry config validates its bounds at construction time, like PostgresPoolConfig does."""
    with pytest.raises(ValueError, match="max attempts"):
        PostgresRetryConfig(max_attempts=0)
    with pytest.raises(ValueError, match="base delay"):
        PostgresRetryConfig(base_delay_seconds=0)


def test_pool_retry_config_from_settings_reads_configured_values() -> None:
    """The settings adapter carries the configured retry bounds through unchanged."""
    settings = SimpleNamespace(
        autodev_postgres_retry_max_attempts=5,
        autodev_postgres_retry_base_delay_seconds=0.2,
    )
    config = pool_retry_config_from_settings(settings)
    assert config.max_attempts == 5
    assert config.base_delay_seconds == 0.2


def test_run_with_postgres_retry_records_a_transient_error_metric_per_classified_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each classified retry attempt reports its error type to the metric sink (E60-S4-T1)."""
    recorded: list[str] = []
    fake_sink = SimpleNamespace(
        record_postgres_transient_error=lambda *, error_type: recorded.append(error_type)
    )
    monkeypatch.setattr(
        "backend.observability.metrics.get_metric_sink", lambda: fake_sink
    )
    attempts = {"count": 0}

    def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _psycopg_error("40P01" if attempts["count"] == 1 else "40001")
        return "ok"

    result = run_with_postgres_retry(
        operation,
        config=PostgresRetryConfig(max_attempts=3, base_delay_seconds=0.001),
        sleep=lambda _seconds: None,
    )

    assert result == "ok"
    assert recorded == ["PostgresDeadlockError", "PostgresSerializationFailureError"]
