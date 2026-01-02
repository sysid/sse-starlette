"""
Throughput and latency tests for sse-starlette.

This module measures the core performance characteristics of the SSE server:
- Raw throughput (events/sec) under various client loads
- Time to first event (connection setup latency)
- Inter-event latency distribution under load

These metrics establish performance baselines and detect regressions in
event delivery, connection handling, and async task scheduling.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from httpx_sse import aconnect_sse

from .baseline import BaselineManager
from .conftest import register_test_report
from .metrics import MetricsCollector
from .reporter import ReportGenerator


@pytest.mark.loadtest
async def test_throughput_single_client(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Measure maximum throughput for a single client.

    ## What is Measured
    - Events per second delivered to a single consumer with zero delay
    - Server's maximum event generation rate without client contention

    ## Why This Matters
    Establishes the performance ceiling for the SSE implementation. A regression
    here indicates fundamental slowdown in event serialization, async scheduling,
    or the streaming response path. This baseline is used to evaluate how well
    throughput scales with multiple clients.

    ## Methodology
    1. Connect single client to /sse?delay=0 (server sends events as fast as possible)
    2. Count events received over 10 seconds
    3. Calculate events/sec throughput

    ## Pass Criteria
    - Throughput >= 1000 events/sec
    - Rationale: With zero delay, the bottleneck should be network I/O and async
      scheduling. 1000 events/sec is achievable on any modern system and leaves
      headroom for real-world latency.
    """
    # Test parameters
    DURATION_SEC = 10

    events_received = 0
    start_time = time.perf_counter()

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with aconnect_sse(
            client, "GET", f"{sse_server_url}/sse?delay=0"
        ) as source:
            async for _ in source.aiter_sse():
                events_received += 1
                if time.perf_counter() - start_time >= DURATION_SEC:
                    break

    elapsed = time.perf_counter() - start_time
    throughput = events_received / elapsed

    # Record metrics
    metrics_collector.add_client_events(events_received)
    metrics_collector.set_duration(elapsed)
    metrics_collector.record_success()

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_throughput_single_client",
        scale=1,
    )
    register_test_report(report)

    # Compare and output
    comparison = baseline_manager.compare(report)
    report.comparison = comparison.to_dict() if comparison else None

    report_generator.save_json(report)
    report_generator.save_html(report, comparison)
    report_generator.print_summary(report, comparison)

    if update_baseline:
        baseline_manager.save_baseline(report)

    # Check for regression
    if fail_on_regression and comparison and comparison.regression_detected:
        pytest.fail(f"Regression detected: {comparison.regression_reasons}")

    # Original assertion
    assert (
        throughput >= 1000
    ), f"Single client throughput {throughput:.0f} events/sec, expected >= 1000"


@pytest.mark.loadtest
async def test_throughput_multiple_clients(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Measure aggregate throughput with multiple concurrent clients.

    ## What is Measured
    - Total events/sec delivered across N concurrent SSE connections
    - Per-client event counts to detect uneven distribution
    - Connection success rate under concurrent load

    ## Why This Matters
    Detects contention issues that only appear under load:
    - Lock contention in the send path (anyio.Lock)
    - Per-connection memory/CPU overhead scaling poorly
    - Async task scheduler saturation
    - Event loop blocking under concurrent I/O

    ## Methodology
    1. Launch NUM_CLIENTS concurrent client tasks
    2. Each client connects to /sse?delay=0.001 (1ms between events)
    3. Run for DURATION_SEC seconds, counting events per client
    4. Sum total events and calculate aggregate throughput

    ## Pass Criteria
    - Aggregate throughput >= min(10000, NUM_CLIENTS * 100) events/sec
    - Rationale: With 1ms delay, each client should receive ~1000 events/sec.
      With 100 clients, expect ~100K events/sec total.
    """
    # Test parameters
    NUM_CLIENTS = 100
    DURATION_SEC = 30

    async def client_task() -> tuple[int, str | None]:
        """Run client and return (event_count, error_or_none)."""
        count = 0
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.001"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if time.perf_counter() - start >= DURATION_SEC:
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    start_time = time.perf_counter()
    tasks = [asyncio.create_task(client_task()) for _ in range(NUM_CLIENTS)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - start_time

    # Process results
    total_events = 0
    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            count, error = result
            metrics_collector.add_client_events(count)
            total_events += count
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    metrics_collector.set_duration(elapsed)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_throughput_multiple_clients",
        scale=NUM_CLIENTS,
    )
    register_test_report(report)

    # Compare and output
    comparison = baseline_manager.compare(report)
    report.comparison = comparison.to_dict() if comparison else None

    report_generator.save_json(report)
    report_generator.save_html(report, comparison)
    report_generator.print_summary(report, comparison)

    if update_baseline:
        baseline_manager.save_baseline(report)

    if fail_on_regression and comparison and comparison.regression_detected:
        pytest.fail(f"Regression detected: {comparison.regression_reasons}")

    # Original assertion
    aggregate_throughput = total_events / elapsed
    min_expected = min(10000, NUM_CLIENTS * 100)
    assert aggregate_throughput >= min_expected, (
        f"Aggregate throughput {aggregate_throughput:.0f} events/sec with {NUM_CLIENTS} "
        f"clients, expected >= {min_expected}"
    )


@pytest.mark.loadtest
async def test_first_event_latency(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Measure time to first event (TTFE) for multiple connections.

    The TTFE is high due to the "thundering herd" effect (100 connections hitting simultaneously).
    But the inter-event latency is excellent - only ~5ms overhead on top of the 10ms delay.

    ## What is Measured
    - Time from connection initiation to first SSE event received
    - Latency distribution across concurrent connections (p50, p99)
    - Connection success rate under concurrent connection storms

    ## Why This Matters
    TTFE is the user-perceived responsiveness metric. High TTFE indicates:
    - Slow connection acceptance in the ASGI server
    - Blocking operations in EventSourceResponse initialization
    - Resource exhaustion during connection setup
    - Inefficient task group initialization

    ## Methodology
    1. Launch NUM_CLIENTS concurrent connection attempts simultaneously
    2. Each client measures time from connect() to first SSE event
    3. Collect latency samples and compute percentiles

    ## Pass Criteria
    - p50 < 1250ms, p99 < 2500ms
    - Calibrated from measured p50=932ms, p99=1779ms at scale=100
    - Threshold factor: 1.3x measured values
    """
    # Test parameters
    NUM_CLIENTS = 100

    async def measure_ttfe() -> tuple[float, str | None]:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0"
                ) as source:
                    async for _ in source.aiter_sse():
                        return (time.perf_counter() - start) * 1000, None
        except Exception as e:
            return -1, str(e)
        return -1, "no events received"

    start_time = time.perf_counter()
    tasks = [asyncio.create_task(measure_ttfe()) for _ in range(NUM_CLIENTS)]
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start_time

    # Process results
    latencies: list[float] = []
    for latency, error in results:
        if latency > 0:
            metrics_collector.add_ttfe_sample(latency)
            metrics_collector.record_success()
            latencies.append(latency)
        else:
            metrics_collector.record_failure(error or "unknown")

    metrics_collector.set_duration(elapsed)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_first_event_latency",
        scale=NUM_CLIENTS,
    )
    register_test_report(report)

    # Compare and output
    comparison = baseline_manager.compare(report)
    report.comparison = comparison.to_dict() if comparison else None

    report_generator.save_json(report)
    report_generator.save_html(report, comparison)
    report_generator.print_summary(report, comparison)

    if update_baseline:
        baseline_manager.save_baseline(report)

    if fail_on_regression and comparison and comparison.regression_detected:
        pytest.fail(f"Regression detected: {comparison.regression_reasons}")

    # Original assertions
    if len(latencies) < NUM_CLIENTS * 0.9:
        pytest.fail(f"Too many failed connections: {len(latencies)}/{NUM_CLIENTS}")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p99 = latencies[int(len(latencies) * 0.99)]

    assert p50 < 1250, f"p50 TTFE {p50:.1f}ms, expected < 1250ms"
    assert p99 < 2500, f"p99 TTFE {p99:.1f}ms, expected < 2500ms"


@pytest.mark.loadtest
async def test_event_latency_under_load(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Measure inter-event latency under concurrent load.

    ## What is Measured
    - Time between consecutive SSE events (inter-event latency)
    - Latency distribution percentiles (p50, p95, p99)
    - Variance across multiple concurrent connections

    ## Why This Matters
    Inter-event latency reveals hidden performance issues:
    - Backpressure from slow sends affecting fast clients
    - Buffer bloat in the response stream
    - Async scheduler starvation under load
    - GC pauses or memory pressure spikes

    Unlike throughput (which averages over time), latency percentiles expose
    tail latency issues that degrade user experience.

    ## Methodology
    1. Launch NUM_CLIENTS concurrent clients to /sse?delay=0.01 (10ms between events)
    2. Each client receives EVENTS_PER_CLIENT events and records inter-event times
    3. Aggregate all latency samples and compute percentiles

    ## Pass Criteria
    - p50 < 20ms, p95 < 30ms, p99 < 40ms
    - Calibrated from measured p50=14.8ms, p95=21.4ms, p99=27.4ms at scale=100
    - Server delay: 10ms. Threshold factor: 1.3x measured values
    """
    # Test parameters
    NUM_CLIENTS = 100
    EVENTS_PER_CLIENT = 100

    async def measure_latencies() -> tuple[list[float], str | None]:
        latencies: list[float] = []
        last_time = None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    count = 0
                    async for _ in source.aiter_sse():
                        now = time.perf_counter()
                        if last_time is not None:
                            latencies.append((now - last_time) * 1000)
                        last_time = now
                        count += 1
                        if count >= EVENTS_PER_CLIENT:
                            break
            return latencies, None
        except Exception as e:
            return latencies, str(e)

    start_time = time.perf_counter()
    tasks = [asyncio.create_task(measure_latencies()) for _ in range(NUM_CLIENTS)]
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start_time

    # Process results
    all_latencies: list[float] = []
    for client_latencies, error in results:
        for lat in client_latencies:
            metrics_collector.add_latency_sample(lat)
            all_latencies.append(lat)
        if error:
            metrics_collector.record_failure(error)
        else:
            metrics_collector.record_success()

    metrics_collector.set_duration(elapsed)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_event_latency_under_load",
        scale=NUM_CLIENTS,
    )
    register_test_report(report)

    # Compare and output
    comparison = baseline_manager.compare(report)
    report.comparison = comparison.to_dict() if comparison else None

    report_generator.save_json(report)
    report_generator.save_html(report, comparison)
    report_generator.print_summary(report, comparison)

    if update_baseline:
        baseline_manager.save_baseline(report)

    if fail_on_regression and comparison and comparison.regression_detected:
        pytest.fail(f"Regression detected: {comparison.regression_reasons}")

    # Original assertions
    if len(all_latencies) < 100:
        pytest.fail(f"Insufficient latency samples: {len(all_latencies)}")

    all_latencies.sort()
    p50 = all_latencies[len(all_latencies) // 2]
    p95 = all_latencies[int(len(all_latencies) * 0.95)]
    p99 = all_latencies[int(len(all_latencies) * 0.99)]

    assert p50 < 20, f"p50 inter-event latency {p50:.1f}ms, expected < 20ms"
    assert p95 < 30, f"p95 inter-event latency {p95:.1f}ms, expected < 30ms"
    assert p99 < 40, f"p99 inter-event latency {p99:.1f}ms, expected < 40ms"
