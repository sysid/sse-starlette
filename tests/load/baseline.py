"""
Baseline management for load test metrics.

Handles loading, saving, and comparing performance baselines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import (
    LatencyStats,
    MemoryStats,
    ReliabilityStats,
    SSEInternals,
    TestReport,
    ThroughputStats,
)


@dataclass
class ComparisonResult:
    """Result of comparing current run against baseline."""

    # Percent changes (positive = worse for latency/memory, negative = worse for throughput)
    latency_p99_change_pct: float | None = None
    latency_p50_change_pct: float | None = None
    ttfe_p99_change_pct: float | None = None
    throughput_change_pct: float | None = None
    memory_growth_change_pct: float | None = None
    memory_slope_change_pct: float | None = None
    error_rate_change_pct: float | None = None

    # Regression detection
    regression_detected: bool = False
    regression_reasons: list[str] | None = None
    warnings: list[str] | None = None

    # Baseline info
    baseline_commit: str | None = None
    baseline_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {}

        if self.baseline_commit:
            result["baseline_commit"] = self.baseline_commit
        if self.baseline_timestamp:
            result["baseline_timestamp"] = self.baseline_timestamp

        if self.latency_p99_change_pct is not None:
            result["latency_p99_change_pct"] = round(self.latency_p99_change_pct, 2)
        if self.latency_p50_change_pct is not None:
            result["latency_p50_change_pct"] = round(self.latency_p50_change_pct, 2)
        if self.ttfe_p99_change_pct is not None:
            result["ttfe_p99_change_pct"] = round(self.ttfe_p99_change_pct, 2)
        if self.throughput_change_pct is not None:
            result["throughput_change_pct"] = round(self.throughput_change_pct, 2)
        if self.memory_growth_change_pct is not None:
            result["memory_growth_change_pct"] = round(self.memory_growth_change_pct, 2)
        if self.memory_slope_change_pct is not None:
            result["memory_slope_change_pct"] = round(self.memory_slope_change_pct, 2)
        if self.error_rate_change_pct is not None:
            result["error_rate_change_pct"] = round(self.error_rate_change_pct, 2)

        result["regression_detected"] = self.regression_detected
        if self.regression_reasons:
            result["regression_reasons"] = self.regression_reasons
        if self.warnings:
            result["warnings"] = self.warnings

        return result


# Default thresholds for regression detection
DEFAULT_THRESHOLDS = {
    "latency_p99_warning_pct": 20.0,
    "latency_p99_fail_pct": 50.0,
    "throughput_warning_pct": -20.0,  # Negative = decrease
    "memory_growth_warning_pct": 50.0,
    "memory_slope_fail": 0.1,  # MB/sec absolute threshold
    "error_rate_fail_pct": 5.0,  # Absolute percentage
}


class BaselineManager:
    """Manages per-test baselines for comparison."""

    def __init__(
        self,
        baselines_dir: Path | str = "tests/load/baselines",
        thresholds: dict[str, float] | None = None,
    ):
        self.baselines_dir = Path(baselines_dir)
        self.thresholds = thresholds or DEFAULT_THRESHOLDS

    def _baseline_path(self, test_name: str) -> Path:
        """Get path to baseline file for a test."""
        # Sanitize test name for filename
        safe_name = test_name.replace("::", "_").replace("/", "_").replace("\\", "_")
        return self.baselines_dir / f"{safe_name}.json"

    def load_baseline(self, test_name: str) -> TestReport | None:
        """Load baseline for a specific test."""
        path = self._baseline_path(test_name)
        if not path.exists():
            return None

        try:
            with open(path) as f:
                data = json.load(f)
            return _dict_to_report(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_baseline(self, report: TestReport) -> Path:
        """Save report as new baseline."""
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        path = self._baseline_path(report.test_name)

        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        return path

    def compare(
        self, current: TestReport, baseline: TestReport | None = None
    ) -> ComparisonResult:
        """Compare current run against baseline."""
        if baseline is None:
            baseline = self.load_baseline(current.test_name)

        if baseline is None:
            return ComparisonResult()

        result = ComparisonResult(
            baseline_commit=baseline.git_commit,
            baseline_timestamp=baseline.timestamp,
        )
        warnings: list[str] = []
        regressions: list[str] = []

        # Compare latency p99
        if current.latency and baseline.latency:
            if baseline.latency.p99_ms > 0:
                change = (
                    (current.latency.p99_ms - baseline.latency.p99_ms)
                    / baseline.latency.p99_ms
                    * 100
                )
                result.latency_p99_change_pct = change
                if change > self.thresholds["latency_p99_fail_pct"]:
                    regressions.append(
                        f"Latency p99 increased by {change:.1f}% "
                        f"(>{self.thresholds['latency_p99_fail_pct']}%)"
                    )
                elif change > self.thresholds["latency_p99_warning_pct"]:
                    warnings.append(f"Latency p99 increased by {change:.1f}%")

            if baseline.latency.p50_ms > 0:
                change = (
                    (current.latency.p50_ms - baseline.latency.p50_ms)
                    / baseline.latency.p50_ms
                    * 100
                )
                result.latency_p50_change_pct = change

        # Compare TTFE p99
        if current.ttfe and baseline.ttfe:
            if baseline.ttfe.p99_ms > 0:
                change = (
                    (current.ttfe.p99_ms - baseline.ttfe.p99_ms)
                    / baseline.ttfe.p99_ms
                    * 100
                )
                result.ttfe_p99_change_pct = change

        # Compare throughput
        if current.throughput and baseline.throughput:
            if baseline.throughput.aggregate_events_per_sec > 0:
                change = (
                    (
                        current.throughput.aggregate_events_per_sec
                        - baseline.throughput.aggregate_events_per_sec
                    )
                    / baseline.throughput.aggregate_events_per_sec
                    * 100
                )
                result.throughput_change_pct = change
                if change < self.thresholds["throughput_warning_pct"]:
                    warnings.append(f"Throughput decreased by {abs(change):.1f}%")

        # Compare memory growth
        if current.memory and baseline.memory:
            if baseline.memory.growth_mb > 0:
                change = (
                    (current.memory.growth_mb - baseline.memory.growth_mb)
                    / baseline.memory.growth_mb
                    * 100
                )
                result.memory_growth_change_pct = change
                if change > self.thresholds["memory_growth_warning_pct"]:
                    warnings.append(f"Memory growth increased by {change:.1f}%")

            # Memory slope absolute check
            if current.memory.slope_mb_per_sec > self.thresholds["memory_slope_fail"]:
                regressions.append(
                    f"Memory slope {current.memory.slope_mb_per_sec:.3f} MB/sec "
                    f"exceeds threshold {self.thresholds['memory_slope_fail']} MB/sec"
                )

            if baseline.memory.slope_mb_per_sec > 0:
                change = (
                    (current.memory.slope_mb_per_sec - baseline.memory.slope_mb_per_sec)
                    / baseline.memory.slope_mb_per_sec
                    * 100
                )
                result.memory_slope_change_pct = change

        # Compare error rate
        if current.reliability and baseline.reliability:
            change = (
                current.reliability.error_rate - baseline.reliability.error_rate
            ) * 100
            result.error_rate_change_pct = change

            if (
                current.reliability.error_rate * 100
                > self.thresholds["error_rate_fail_pct"]
            ):
                regressions.append(
                    f"Error rate {current.reliability.error_rate * 100:.1f}% "
                    f"exceeds threshold {self.thresholds['error_rate_fail_pct']}%"
                )

        result.regression_detected = len(regressions) > 0
        result.regression_reasons = regressions if regressions else None
        result.warnings = warnings if warnings else None

        return result


def _dict_to_report(data: dict[str, Any]) -> TestReport:
    """Convert JSON dict back to TestReport."""
    metadata = data.get("metadata", data)

    # Reconstruct latency stats
    latency = None
    if "latency" in data:
        lat = data["latency"]
        latency = LatencyStats(
            p50_ms=lat["p50_ms"],
            p90_ms=lat["p90_ms"],
            p95_ms=lat["p95_ms"],
            p99_ms=lat["p99_ms"],
            max_ms=lat["max_ms"],
            min_ms=lat.get("min_ms", 0.0),
            mean_ms=lat["mean_ms"],
            stdev_ms=lat["stdev_ms"],
            sample_count=lat["sample_count"],
        )

    ttfe = None
    if "ttfe" in data:
        t = data["ttfe"]
        ttfe = LatencyStats(
            p50_ms=t["p50_ms"],
            p90_ms=t["p90_ms"],
            p95_ms=t["p95_ms"],
            p99_ms=t["p99_ms"],
            max_ms=t["max_ms"],
            min_ms=t.get("min_ms", 0.0),
            mean_ms=t["mean_ms"],
            stdev_ms=t["stdev_ms"],
            sample_count=t["sample_count"],
        )

    throughput = None
    if "throughput" in data:
        th = data["throughput"]
        throughput = ThroughputStats(
            aggregate_events_per_sec=th["aggregate_events_per_sec"],
            per_client_events_per_sec=th["per_client_events_per_sec"],
            total_events=th["total_events"],
            total_duration_sec=th["total_duration_sec"],
            client_count=th["client_count"],
        )

    memory = None
    if "memory" in data:
        m = data["memory"]
        memory = MemoryStats(
            baseline_mb=m["baseline_mb"],
            peak_mb=m["peak_mb"],
            final_mb=m["final_mb"],
            growth_mb=m["growth_mb"],
            slope_mb_per_sec=m["slope_mb_per_sec"],
            samples=[(s[0], s[1]) for s in m.get("samples", [])],
        )

    reliability = None
    if "reliability" in data:
        r = data["reliability"]
        reliability = ReliabilityStats(
            successful_connections=r["successful_connections"],
            failed_connections=r["failed_connections"],
            error_rate=r["error_rate"],
            errors=r.get("errors", []),
        )

    sse_internals = None
    if "sse_internals" in data:
        s = data["sse_internals"]
        sse_internals = SSEInternals(
            watcher_started=s["watcher_started"],
            peak_registered_events=s["peak_registered_events"],
            final_registered_events=s["final_registered_events"],
        )

    return TestReport(
        test_name=metadata.get("test_name", "unknown"),
        timestamp=metadata.get("timestamp", ""),
        git_commit=metadata.get("git_commit", "unknown"),
        git_branch=metadata.get("git_branch", "unknown"),
        scale=metadata.get("scale", 0),
        duration_minutes=metadata.get("duration_minutes", 0),
        latency=latency,
        ttfe=ttfe,
        throughput=throughput,
        memory=memory,
        reliability=reliability,
        sse_internals=sse_internals,
        comparison=data.get("comparison"),
    )
