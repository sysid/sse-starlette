"""
Core metrics collection and reporting infrastructure for load tests.

Provides dataclasses for structured metrics and a collector for aggregating
samples during test execution.
"""

from __future__ import annotations

import statistics
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class LatencyStats:
    """Statistical summary of latency measurements."""

    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    min_ms: float
    mean_ms: float
    stdev_ms: float
    sample_count: int

    @classmethod
    def from_samples(cls, samples: list[float]) -> LatencyStats | None:
        """Compute statistics from raw latency samples (in ms)."""
        if not samples:
            return None

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        def percentile(p: float) -> float:
            idx = int(n * p / 100)
            return sorted_samples[min(idx, n - 1)]

        return cls(
            p50_ms=percentile(50),
            p90_ms=percentile(90),
            p95_ms=percentile(95),
            p99_ms=percentile(99),
            max_ms=sorted_samples[-1],
            min_ms=sorted_samples[0],
            mean_ms=statistics.mean(sorted_samples),
            stdev_ms=statistics.stdev(sorted_samples) if n > 1 else 0.0,
            sample_count=n,
        )

    def to_dict(self) -> dict[str, float | int]:
        """Convert to JSON-serializable dict."""
        return {
            "p50_ms": round(self.p50_ms, 3),
            "p90_ms": round(self.p90_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "stdev_ms": round(self.stdev_ms, 3),
            "sample_count": self.sample_count,
        }


@dataclass
class MemoryStats:
    """Memory usage statistics."""

    baseline_mb: float
    peak_mb: float
    final_mb: float
    growth_mb: float
    slope_mb_per_sec: float
    samples: list[tuple[float, float]]  # (elapsed_sec, rss_mb)

    @classmethod
    def from_samples(
        cls,
        samples: list[tuple[float, float]],
        baseline_mb: float,
        final_mb: float,
    ) -> MemoryStats:
        """Compute statistics from time-series memory samples."""
        if not samples:
            return cls(
                baseline_mb=baseline_mb,
                peak_mb=baseline_mb,
                final_mb=final_mb,
                growth_mb=0.0,
                slope_mb_per_sec=0.0,
                samples=[],
            )

        peak_mb = max(s[1] for s in samples)
        growth_mb = peak_mb - baseline_mb

        # Linear regression for slope
        slope = 0.0
        if len(samples) >= 2:
            x_vals = [s[0] for s in samples]
            y_vals = [s[1] for s in samples]
            x_mean = statistics.mean(x_vals)
            y_mean = statistics.mean(y_vals)
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
            denominator = sum((x - x_mean) ** 2 for x in x_vals)
            if denominator > 0:
                slope = numerator / denominator

        return cls(
            baseline_mb=baseline_mb,
            peak_mb=peak_mb,
            final_mb=final_mb,
            growth_mb=growth_mb,
            slope_mb_per_sec=slope,
            samples=samples,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "baseline_mb": round(self.baseline_mb, 2),
            "peak_mb": round(self.peak_mb, 2),
            "final_mb": round(self.final_mb, 2),
            "growth_mb": round(self.growth_mb, 2),
            "slope_mb_per_sec": round(self.slope_mb_per_sec, 4),
            "samples": [[round(t, 2), round(m, 2)] for t, m in self.samples],
        }


@dataclass
class ThroughputStats:
    """Throughput statistics."""

    aggregate_events_per_sec: float
    per_client_events_per_sec: float
    total_events: int
    total_duration_sec: float
    client_count: int

    def to_dict(self) -> dict[str, float | int]:
        """Convert to JSON-serializable dict."""
        return {
            "aggregate_events_per_sec": round(self.aggregate_events_per_sec, 2),
            "per_client_events_per_sec": round(self.per_client_events_per_sec, 2),
            "total_events": self.total_events,
            "total_duration_sec": round(self.total_duration_sec, 2),
            "client_count": self.client_count,
        }


@dataclass
class ReliabilityStats:
    """Connection reliability statistics."""

    successful_connections: int
    failed_connections: int
    error_rate: float
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "successful_connections": self.successful_connections,
            "failed_connections": self.failed_connections,
            "error_rate": round(self.error_rate, 4),
            "errors": self.errors[:10],  # Limit to first 10 errors
        }


@dataclass
class SSEInternals:
    """SSE library internal state (Issue #152 validation)."""

    watcher_started: bool
    peak_registered_events: int
    final_registered_events: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "watcher_started": self.watcher_started,
            "peak_registered_events": self.peak_registered_events,
            "final_registered_events": self.final_registered_events,
        }


@dataclass
class TestReport:
    """Complete performance report for a single test."""

    test_name: str
    timestamp: str
    git_commit: str
    git_branch: str
    scale: int
    duration_minutes: int

    # Metrics (optional based on test type)
    latency: LatencyStats | None = None
    ttfe: LatencyStats | None = None
    throughput: ThroughputStats | None = None
    memory: MemoryStats | None = None
    reliability: ReliabilityStats | None = None
    sse_internals: SSEInternals | None = None

    # Comparison results (populated by BaselineManager)
    comparison: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {
            "metadata": {
                "test_name": self.test_name,
                "timestamp": self.timestamp,
                "git_commit": self.git_commit,
                "git_branch": self.git_branch,
                "scale": self.scale,
                "duration_minutes": self.duration_minutes,
            }
        }

        if self.latency:
            result["latency"] = self.latency.to_dict()
        if self.ttfe:
            result["ttfe"] = self.ttfe.to_dict()
        if self.throughput:
            result["throughput"] = self.throughput.to_dict()
        if self.memory:
            result["memory"] = self.memory.to_dict()
        if self.reliability:
            result["reliability"] = self.reliability.to_dict()
        if self.sse_internals:
            result["sse_internals"] = self.sse_internals.to_dict()
        if self.comparison:
            result["comparison"] = self.comparison

        return result


def _get_git_info() -> tuple[str, str]:
    """Get current git commit and branch."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        commit = "unknown"

    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        branch = "unknown"

    return commit, branch


@dataclass
class MetricsCollector:
    """Collects performance metrics during test execution."""

    # Latency samples (milliseconds)
    latency_samples: list[float] = field(default_factory=list)
    ttfe_samples: list[float] = field(default_factory=list)

    # Memory samples (elapsed_sec, rss_mb)
    memory_samples: list[tuple[float, float]] = field(default_factory=list)
    memory_baseline_mb: float = 0.0
    memory_final_mb: float = 0.0

    # Throughput tracking
    events_per_client: list[int] = field(default_factory=list)
    total_duration_sec: float = 0.0

    # Reliability
    successful_connections: int = 0
    failed_connections: int = 0
    errors: list[str] = field(default_factory=list)

    # SSE internals
    watcher_started: bool = False
    peak_registered_events: int = 0
    final_registered_events: int = 0

    # Internal timing
    _start_time: float = field(default_factory=time.perf_counter)

    def add_latency_sample(self, ms: float) -> None:
        """Record an inter-event latency sample."""
        self.latency_samples.append(ms)

    def add_ttfe_sample(self, ms: float) -> None:
        """Record a time-to-first-event sample."""
        self.ttfe_samples.append(ms)

    def add_memory_sample(self, rss_mb: float) -> None:
        """Record a memory usage sample with timestamp."""
        elapsed = time.perf_counter() - self._start_time
        self.memory_samples.append((elapsed, rss_mb))

    def set_memory_baseline(self, rss_mb: float) -> None:
        """Set the baseline memory before test starts."""
        self.memory_baseline_mb = rss_mb

    def set_memory_final(self, rss_mb: float) -> None:
        """Set the final memory after test completes."""
        self.memory_final_mb = rss_mb

    def add_client_events(self, count: int) -> None:
        """Record events received by a client."""
        self.events_per_client.append(count)

    def set_duration(self, seconds: float) -> None:
        """Set total test duration."""
        self.total_duration_sec = seconds

    def record_success(self) -> None:
        """Record a successful connection."""
        self.successful_connections += 1

    def record_failure(self, error: str) -> None:
        """Record a failed connection."""
        self.failed_connections += 1
        self.errors.append(error)

    def set_sse_internals(
        self, watcher_started: bool, peak_events: int, final_events: int
    ) -> None:
        """Record SSE library internal state."""
        self.watcher_started = watcher_started
        self.peak_registered_events = peak_events
        self.final_registered_events = final_events

    def compute_report(self, test_name: str, scale: int) -> TestReport:
        """Compute final report from collected samples."""
        git_commit, git_branch = _get_git_info()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Compute latency stats
        latency = LatencyStats.from_samples(self.latency_samples)
        ttfe = LatencyStats.from_samples(self.ttfe_samples)

        # Compute memory stats
        memory = None
        if self.memory_samples or self.memory_baseline_mb > 0:
            memory = MemoryStats.from_samples(
                self.memory_samples,
                self.memory_baseline_mb,
                self.memory_final_mb,
            )

        # Compute throughput stats
        throughput = None
        if self.events_per_client and self.total_duration_sec > 0:
            total_events = sum(self.events_per_client)
            client_count = len(self.events_per_client)
            throughput = ThroughputStats(
                aggregate_events_per_sec=total_events / self.total_duration_sec,
                per_client_events_per_sec=(
                    (total_events / client_count / self.total_duration_sec)
                    if client_count > 0
                    else 0.0
                ),
                total_events=total_events,
                total_duration_sec=self.total_duration_sec,
                client_count=client_count,
            )

        # Compute reliability stats
        total_connections = self.successful_connections + self.failed_connections
        reliability = None
        if total_connections > 0:
            reliability = ReliabilityStats(
                successful_connections=self.successful_connections,
                failed_connections=self.failed_connections,
                error_rate=(
                    self.failed_connections / total_connections
                    if total_connections > 0
                    else 0.0
                ),
                errors=self.errors,
            )

        # SSE internals
        sse_internals = None
        if self.peak_registered_events > 0 or self.watcher_started:
            sse_internals = SSEInternals(
                watcher_started=self.watcher_started,
                peak_registered_events=self.peak_registered_events,
                final_registered_events=self.final_registered_events,
            )

        # Compute duration_minutes from actual test duration
        duration_minutes = max(1, int(self.total_duration_sec / 60))

        return TestReport(
            test_name=test_name,
            timestamp=timestamp,
            git_commit=git_commit,
            git_branch=git_branch,
            scale=scale,
            duration_minutes=duration_minutes,
            latency=latency,
            ttfe=ttfe,
            throughput=throughput,
            memory=memory,
            reliability=reliability,
            sse_internals=sse_internals,
        )
