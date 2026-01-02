"""
Memory stability tests for sse-starlette under load.

This module detects memory leaks and resource accumulation in the SSE implementation:
- Memory growth during sustained streaming (leak detection)
- Memory reclamation after connections close (cleanup verification)
- Internal event set cleanup (Issue #152 regression test)

Memory leaks in SSE are particularly insidious because they accumulate slowly
over days/weeks in production, eventually causing OOM kills.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx_sse import aconnect_sse

from .baseline import BaselineManager
from .conftest import register_test_report
from .metrics import MetricsCollector
from .reporter import ReportGenerator


@pytest.mark.loadtest
async def test_memory_stability_under_load(
    sse_server_url: str,
    scale: int,
    duration_minutes: int,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify memory remains stable during sustained SSE streaming.

    ## What is Measured
    - RSS memory at start, during streaming, and at end
    - Total memory growth (peak - baseline)
    - Memory growth rate (linear regression slope over time samples)

    ## Why This Matters
    Detects memory leaks in the EventSourceResponse lifecycle:
    - Buffers not released after send
    - Task references held after completion
    - Event objects accumulating in queues
    - Closure captures preventing garbage collection

    A small leak (e.g., 1KB/connection) becomes catastrophic with thousands of
    connections over hours of operation.

    ## Methodology
    1. Record baseline memory before any connections
    2. Connect `scale` clients, each streaming for `duration_minutes`
    3. Sample memory periodically during streaming
    4. Compute total growth and growth rate (slope)

    ## Pass Criteria
    - Memory growth < 50MB total
    - Growth rate (slope) < 0.1 MB/sec
    - Rationale: 50MB allows for legitimate per-connection overhead while
      catching runaway leaks. The slope check catches slow leaks that might
      stay under the absolute threshold but indicate unbounded growth.
    """
    events_per_client = duration_minutes * 60 * 10  # 10 events/sec

    async def client_task(client_id: int) -> tuple[int, str | None]:
        """Single client consuming SSE events."""
        events_received = 0
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.1"
                ) as source:
                    async for _ in source.aiter_sse():
                        events_received += 1
                        if events_received >= events_per_client:
                            break
            return events_received, None
        except Exception as e:
            return events_received, str(e)

    # Get baseline memory
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_memory = baseline["memory_rss_mb"]
    metrics_collector.set_memory_baseline(baseline_memory)

    # Start all clients
    tasks = [asyncio.create_task(client_task(i)) for i in range(scale)]

    # Sample memory periodically
    sample_interval = max(10, duration_minutes * 6)  # At least 10 samples

    for _ in range(sample_interval):
        await asyncio.sleep(duration_minutes * 60 / sample_interval)
        try:
            async with httpx.AsyncClient() as client:
                metrics = (await client.get(f"{sse_server_url}/metrics")).json()
                metrics_collector.add_memory_sample(metrics["memory_rss_mb"])
        except Exception:
            pass  # Server might be under heavy load

    # Wait for all clients to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            events, error = result
            metrics_collector.add_client_events(events)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Get final memory
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_memory = final["memory_rss_mb"]
    metrics_collector.set_memory_final(final_memory)

    # Set duration
    metrics_collector.set_duration(duration_minutes * 60)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_memory_stability_under_load",
        scale=scale,
        duration_minutes=duration_minutes,
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
    completed = metrics_collector.successful_connections
    assert (
        completed >= scale * 0.9
    ), f"Too many failed connections: {completed}/{scale} completed"

    if report.memory:
        assert report.memory.growth_mb < 50, (
            f"Memory grew by {report.memory.growth_mb:.1f}MB "
            f"(baseline: {baseline_memory:.1f}MB, peak: {report.memory.peak_mb:.1f}MB), "
            f"expected < 50MB"
        )
        assert report.memory.slope_mb_per_sec < 0.1, (
            f"Memory growth trend {report.memory.slope_mb_per_sec:.3f} MB/sec, "
            f"expected < 0.1 MB/sec"
        )


@pytest.mark.loadtest
async def test_memory_returns_to_baseline_after_disconnect(
    sse_server_url: str,
    scale: int,
    duration_minutes: int,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify memory is reclaimed after all connections close.

    ## What is Measured
    - Memory before any connections (baseline)
    - Memory after all connections close (final)
    - Delta as percentage of baseline

    ## Why This Matters
    Complements the stability test by verifying cleanup:
    - Task references properly released
    - anyio.Event objects garbage collected
    - No lingering closures or callbacks
    - Thread-local state cleared

    Even if memory doesn't grow during streaming, retained references after
    disconnect indicate a leak that will accumulate across connection cycles.

    ## Methodology
    1. Record baseline memory
    2. Connect clients in batches, each receiving 50 events then disconnecting
    3. Wait 2 seconds for cleanup (GC, finalizers)
    4. Record final memory and compare to baseline

    ## Pass Criteria
    - Final memory <= baseline * 1.2 (20% margin)
    - Rationale: Python's memory allocator doesn't always return memory to OS
      immediately. 20% margin accounts for fragmentation and GC timing while
      still catching significant retention issues.
    """

    async def client_task(client_id: int) -> tuple[int, str | None]:
        """Client that connects, receives few events, then disconnects."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    count = 0
                    async for _ in source.aiter_sse():
                        count += 1
                        if count >= 50:
                            break
            return count, None
        except Exception as e:
            return 0, str(e)

    # Get baseline
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_memory = baseline["memory_rss_mb"]
    metrics_collector.set_memory_baseline(baseline_memory)

    # Connect and disconnect clients in batches
    batch_size = min(100, scale)
    for batch_start in range(0, scale, batch_size):
        batch_end = min(batch_start + batch_size, scale)
        tasks = [
            asyncio.create_task(client_task(i)) for i in range(batch_start, batch_end)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                metrics_collector.record_failure(str(result))
            elif isinstance(result, tuple):
                events, error = result
                metrics_collector.add_client_events(events)
                if error:
                    metrics_collector.record_failure(error)
                else:
                    metrics_collector.record_success()

        # Sample memory after each batch
        try:
            async with httpx.AsyncClient() as client:
                metrics = (await client.get(f"{sse_server_url}/metrics")).json()
                metrics_collector.add_memory_sample(metrics["memory_rss_mb"])
        except Exception:
            pass

    # Wait for cleanup
    await asyncio.sleep(2)

    # Check memory returned to near baseline
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_memory = final["memory_rss_mb"]
    metrics_collector.set_memory_final(final_memory)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_memory_returns_to_baseline_after_disconnect",
        scale=scale,
        duration_minutes=duration_minutes,
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
    max_allowed = baseline_memory * 1.2
    assert final_memory <= max_allowed, (
        f"Memory did not return to baseline: {final_memory:.1f}MB "
        f"(baseline: {baseline_memory:.1f}MB, max allowed: {max_allowed:.1f}MB)"
    )


@pytest.mark.loadtest
async def test_event_set_cleanup(
    sse_server_url: str,
    scale: int,
    duration_minutes: int,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify internal event set is cleaned up after connections close (Issue #152).

    ## What is Measured
    - `registered_events` count from /metrics endpoint
    - Events at baseline, peak (during connections), and after cleanup
    - Watcher started status (should be True if connections exist)

    ## Why This Matters
    This is a regression test for Issue #152 (watcher task leak). Before the fix:
    - Each SSE connection created a new watcher task
    - Events accumulated in `_ShutdownState.events` without cleanup
    - CPU usage grew unbounded as N watchers polled AppStatus.should_exit

    After the fix (using threading.local):
    - One watcher per thread, not per connection
    - Events removed from set on connection close
    - Watcher stops when set becomes empty

    ## Methodology
    1. Record baseline `registered_events` count
    2. Connect `scale` clients, wait for connections to establish
    3. Record peak `registered_events` (should be >= scale * 0.2)
    4. Wait for all connections to close + 2s cleanup
    5. Record final `registered_events` (should return near baseline)

    ## Pass Criteria
    - Peak events >= scale * 0.2 (events were registered)
    - Final events <= baseline + 10 (events were cleaned up)
    - Rationale: We expect most (not all) connections to register events.
      After cleanup, the set should be nearly empty. The +10 margin allows
      for concurrent test interference.
    """

    connected = asyncio.Event()
    connection_count = 0

    async def client_task() -> tuple[int, str | None]:
        nonlocal connection_count
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.5"
                ) as source:
                    connection_count += 1
                    if connection_count >= scale * 0.5:
                        connected.set()
                    count = 0
                    async for _ in source.aiter_sse():
                        count += 1
                        if count >= 5:  # Stay connected for ~2.5s
                            break
            return count, None
        except Exception as e:
            return 0, str(e)

    # Get baseline event count
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_events = baseline["registered_events"]
    baseline_memory = baseline["memory_rss_mb"]
    metrics_collector.set_memory_baseline(baseline_memory)

    # Connect many clients
    tasks = [asyncio.create_task(client_task()) for _ in range(scale)]

    # Wait for connections to establish (with timeout)
    try:
        await asyncio.wait_for(connected.wait(), timeout=10)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0.5)  # Extra margin

    # Check events registered during peak
    async with httpx.AsyncClient() as client:
        peak = (await client.get(f"{sse_server_url}/metrics")).json()
    peak_events = peak["registered_events"]
    metrics_collector.add_memory_sample(peak["memory_rss_mb"])

    # Wait for all to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            events, error = result
            metrics_collector.add_client_events(events)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    await asyncio.sleep(2)  # Allow cleanup time

    # Check events cleaned up
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_events = final["registered_events"]
    metrics_collector.set_memory_final(final["memory_rss_mb"])

    # Record SSE internals
    metrics_collector.set_sse_internals(
        watcher_started=peak.get("watcher_started", False),
        peak_events=peak_events,
        final_events=final_events,
    )

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_event_set_cleanup",
        scale=scale,
        duration_minutes=duration_minutes,
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
    assert peak_events >= scale * 0.2, (
        f"Expected at least {scale * 0.2} events registered during peak, "
        f"got {peak_events}"
    )
    assert final_events <= baseline_events + 10, (
        f"Event set not cleaned up: {final_events} events remaining "
        f"(baseline: {baseline_events})"
    )
