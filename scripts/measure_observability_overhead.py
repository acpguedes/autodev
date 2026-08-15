"""Measure OpenTelemetry instrumentation overhead against a synthetic workload."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config.settings import Settings  # noqa: E402
from backend.observability.runtime import configure_observability  # noqa: E402
from backend.observability.tracing import trace_run, trace_run_step  # noqa: E402

TARGET_RATIO = 0.05
DEFAULT_ROUNDS = 7
DEFAULT_ITERATIONS_PER_ROUND = 200
DEFAULT_WORKLOAD_SECONDS = 0.005


@dataclass(frozen=True)
class OverheadResult:
    """Paired median timing comparison between baseline and instrumented runs.

    Attributes:
        baseline_seconds: Median duration of the uninstrumented rounds.
        instrumented_seconds: Median duration of the instrumented rounds.
        overhead_ratio: Instrumentation cost relative to the baseline.
        rounds: Number of alternated rounds measured for each path.
        iterations_per_round: Workload repetitions performed per round.
    """

    baseline_seconds: float
    instrumented_seconds: float
    overhead_ratio: float
    rounds: int
    iterations_per_round: int

    @property
    def within_target(self) -> bool:
        """Return whether the measured overhead stays under the NFR target."""
        return self.overhead_ratio < TARGET_RATIO


def calculate_overhead_ratio(
    baseline_seconds: float, instrumented_seconds: float
) -> float:
    """Compute instrumentation overhead relative to the baseline duration.

    Args:
        baseline_seconds: Median uninstrumented duration.
        instrumented_seconds: Median instrumented duration.

    Returns:
        The fractional overhead, e.g. ``0.04`` for a 4% increase.
    """
    return (instrumented_seconds - baseline_seconds) / baseline_seconds


def _wait(seconds: float) -> None:
    """Busy-wait for a deterministic duration to simulate representative I/O.

    ``time.sleep`` hands control back to the OS scheduler, whose wake-up
    granularity and jitter (worst on this WSL2 development environment) is
    frequently larger than the ~80us instrumentation overhead this benchmark
    measures, drowning the signal in scheduler noise rather than measuring
    instrumentation cost. Spinning on a monotonic clock keeps the thread
    runnable so both paths see the same, tight wall-clock wait.

    Args:
        seconds: Wait duration.
    """
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        pass


def _baseline_operation(workload_seconds: float) -> None:
    """Perform the representative workload with no instrumentation.

    Args:
        workload_seconds: Simulated I/O wait duration.
    """
    _wait(workload_seconds)


def _instrumented_operation(workload_seconds: float) -> None:
    """Perform the representative workload wrapped in a run and step trace.

    Args:
        workload_seconds: Simulated I/O wait duration.
    """
    with trace_run(
        run_id="overhead-run", tenant_id="overhead-tenant", flow_id="overhead-flow"
    ) as run:
        with trace_run_step(
            run_id="overhead-run",
            step_id="overhead-step",
            agent="overhead-agent",
            tenant_id="overhead-tenant",
        ) as step:
            _wait(workload_seconds)
            step.finish(status="completed")
        run.finish(status="completed")


def _run_round(operation, iterations: int, workload_seconds: float) -> float:
    """Time one round of repeated workload iterations.

    Args:
        operation: Zero-argument callable performing one workload iteration.
        iterations: Number of iterations to perform in this round.
        workload_seconds: Simulated I/O wait passed to each iteration.

    Returns:
        Wall-clock duration of the round, in seconds.
    """
    started = time.perf_counter()
    for _ in range(iterations):
        operation(workload_seconds)
    return time.perf_counter() - started


def measure_overhead(
    *,
    rounds: int = DEFAULT_ROUNDS,
    iterations_per_round: int = DEFAULT_ITERATIONS_PER_ROUND,
    workload_seconds: float = DEFAULT_WORKLOAD_SECONDS,
) -> OverheadResult:
    """Measure paired-median instrumentation overhead against a synthetic workload.

    Alternates which path runs first each round to cancel systematic drift
    (cache warmth, scheduler noise) between the baseline and instrumented
    measurements. The instrumented path uses an always-on SDK provider with
    no exporter configured, matching production's nonblocking batch-export
    code path without depending on a live Collector.

    Args:
        rounds: Number of alternated rounds measured for each path.
        iterations_per_round: Workload repetitions performed per round.
        workload_seconds: Simulated I/O wait duration per iteration.

    Returns:
        The paired median overhead measurement.
    """
    # The JSON log handler binds to whatever `sys.stdout` object is current
    # when `configure_observability` runs, not to `sys.stdout` dynamically,
    # so redirecting only for this call is enough to send every instrumented
    # log line to a null stream for the remainder of the benchmark.
    devnull = open(os.devnull, "w", encoding="utf-8")
    previous_stdout = sys.stdout
    sys.stdout = devnull
    try:
        runtime = configure_observability(
            Settings(otel_enabled=True),
            install_global=False,
        )
    finally:
        sys.stdout = previous_stdout

    try:
        # Warm up both paths once outside the measured rounds so import,
        # first-span, and first-log costs do not bias the first round.
        _baseline_operation(workload_seconds)
        _instrumented_operation(workload_seconds)

        baseline_rounds: list[float] = []
        instrumented_rounds: list[float] = []
        for round_index in range(rounds):
            if round_index % 2 == 0:
                baseline_rounds.append(
                    _run_round(_baseline_operation, iterations_per_round, workload_seconds)
                )
                instrumented_rounds.append(
                    _run_round(
                        _instrumented_operation, iterations_per_round, workload_seconds
                    )
                )
            else:
                instrumented_rounds.append(
                    _run_round(
                        _instrumented_operation, iterations_per_round, workload_seconds
                    )
                )
                baseline_rounds.append(
                    _run_round(_baseline_operation, iterations_per_round, workload_seconds)
                )
    finally:
        runtime.shutdown()
        devnull.close()

    baseline_seconds = statistics.median(baseline_rounds)
    instrumented_seconds = statistics.median(instrumented_rounds)
    return OverheadResult(
        baseline_seconds=baseline_seconds,
        instrumented_seconds=instrumented_seconds,
        overhead_ratio=calculate_overhead_ratio(baseline_seconds, instrumented_seconds),
        rounds=rounds,
        iterations_per_round=iterations_per_round,
    )


def main() -> int:
    """Run the benchmark, print its JSON result, and signal target compliance.

    Returns:
        Zero when the measured overhead is within target; one otherwise.
    """
    result = measure_overhead(workload_seconds=DEFAULT_WORKLOAD_SECONDS)
    print(
        json.dumps(
            {
                "baseline_seconds": result.baseline_seconds,
                "instrumented_seconds": result.instrumented_seconds,
                "overhead_ratio": result.overhead_ratio,
                "target_ratio": TARGET_RATIO,
                "within_target": result.within_target,
                "rounds": result.rounds,
                "iterations_per_round": result.iterations_per_round,
                "workload_seconds": DEFAULT_WORKLOAD_SECONDS,
            }
        )
    )
    return 0 if result.within_target else 1


if __name__ == "__main__":
    raise SystemExit(main())
