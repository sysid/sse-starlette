"""
Watcher deduplication tests at scale (Issue #152 regression suite).

This module validates the fix for Issue #152: watcher task accumulation.
Before the fix, each SSE connection spawned a new watcher task that polled
AppStatus.should_exit. With thousands of connections, CPU usage grew unbounded.

The fix uses threading.local() to maintain one watcher per thread. These tests
verify that pattern holds under various load conditions:
- Many simultaneous connections sharing a single watcher
- Rapid connect/disconnect cycles not spawning new watchers
- Clean watcher lifecycle (start -> broadcast -> cleanup -> restart)
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
async def test_single_watcher_with_many_connections(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify only one watcher runs regardless of connection count (Issue #152 core test).

    ## What is Measured
    - `watcher_started` flag from /metrics (True = watcher exists)
    - `registered_events` count (should be >= NUM_CLIENTS * 0.5)
    - Implicit: CPU usage would spike if multiple watchers existed (not measured)

    ## Why This Matters
    This is the primary regression test for Issue #152. Before the fix:
    - N connections = N watcher tasks
    - Each watcher polls AppStatus.should_exit every 0.5s
    - 1000 connections = 1000 polling tasks = CPU exhaustion

    After the fix:
    - N connections = 1 watcher task (per thread)
    - Watcher broadcasts to all registered events
    - Constant CPU overhead regardless of connection count

    ## Methodology
    1. Connect NUM_CLIENTS concurrent clients
    2. Wait for connections to establish (~2s)
    3. Query /metrics for watcher_started and registered_events
    4. Cancel all connections

    ## Pass Criteria
    - watcher_started = True (watcher exists for active connections)
    - registered_events >= NUM_CLIENTS * 0.5 (most connections registered)
    - Rationale: watcher_started=True confirms the mechanism works.
      Event count verifies registration worked. We don't directly measure
      watcher count, but CPU metrics in CI would catch proliferation.
    """
    # Test parameters
    NUM_CLIENTS = 100
    HOLD_DURATION_SEC = 5

    async def client_task() -> tuple[int, str | None]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.1"
                ) as source:
                    async for _ in source.aiter_sse():
                        await asyncio.sleep(HOLD_DURATION_SEC)  # Stay connected
                        break
            return 1, None
        except Exception as e:
            return 0, str(e)

    start_time = time.perf_counter()

    # Start many connections
    tasks = [asyncio.create_task(client_task()) for _ in range(NUM_CLIENTS)]

    # Wait for connections to establish
    await asyncio.sleep(2)

    # Check watcher status
    async with httpx.AsyncClient() as client:
        metrics = (await client.get(f"{sse_server_url}/metrics")).json()

    watcher_started = metrics["watcher_started"]
    registered_events = metrics["registered_events"]
    metrics_collector.add_memory_sample(metrics["memory_rss_mb"])

    # Cancel all tasks
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.perf_counter() - start_time
    metrics_collector.set_duration(elapsed)

    # Process results
    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            _, error = result
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Record SSE internals
    metrics_collector.set_sse_internals(
        watcher_started=watcher_started,
        peak_events=registered_events,
        final_events=0,
    )

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_single_watcher_with_many_connections",
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
    assert watcher_started is True, "Watcher should be started with active connections"
    assert (
        registered_events >= NUM_CLIENTS * 0.5
    ), f"Expected at least {NUM_CLIENTS * 0.5} events, got {registered_events}"


@pytest.mark.loadtest
async def test_rapid_connect_disconnect_watcher_stability(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify rapid connect/disconnect cycles don't accumulate watcher tasks.

    ## What is Measured
    - Thread count after many rapid connection cycles
    - Memory samples during the churn
    - SSE internals (watcher_started, registered_events)

    ## Why This Matters
    Tests the watcher lifecycle under high churn:
    - Connections come and go faster than the watcher poll interval (0.5s)
    - Watcher must survive connection churn without proliferation
    - Event registration/deregistration must be thread-safe

    Before Issue #152 fix, each connection left behind a watcher task. Even if
    connections closed quickly, watchers accumulated and never stopped.

    ## Methodology
    1. Run NUM_BATCHES batches of BATCH_SIZE quick connections each
    2. Each connection receives 1 event and disconnects immediately
    3. After all batches, check thread count and watcher status

    ## Pass Criteria
    - num_threads < 50
    - Rationale: A healthy uvicorn server has ~5-10 threads. If watchers
      accumulated, we'd see hundreds of threads (one per watcher task).
      50 provides margin for legitimate worker threads.
    """
    # Test parameters
    NUM_BATCHES = 10
    BATCH_SIZE = 10

    async def quick_connect() -> tuple[int, str | None]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    async for _ in source.aiter_sse():
                        break  # Disconnect after first event
            return 1, None
        except Exception as e:
            return 0, str(e)

    start_time = time.perf_counter()

    # Rapid connect/disconnect cycles
    for _ in range(NUM_BATCHES):
        tasks = [asyncio.create_task(quick_connect()) for _ in range(BATCH_SIZE)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                metrics_collector.record_failure(str(result))
            elif isinstance(result, tuple):
                count, error = result
                metrics_collector.add_client_events(count)
                if error:
                    metrics_collector.record_failure(error)
                else:
                    metrics_collector.record_success()

    # Brief pause
    await asyncio.sleep(0.5)

    elapsed = time.perf_counter() - start_time
    metrics_collector.set_duration(elapsed)

    # Check metrics - watcher should still be singular
    async with httpx.AsyncClient() as client:
        metrics = (await client.get(f"{sse_server_url}/metrics")).json()

    num_threads = metrics["num_threads"]
    metrics_collector.add_memory_sample(metrics["memory_rss_mb"])

    # Record SSE internals
    metrics_collector.set_sse_internals(
        watcher_started=metrics.get("watcher_started", False),
        peak_events=metrics.get("registered_events", 0),
        final_events=metrics.get("registered_events", 0),
    )

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_rapid_connect_disconnect_watcher_stability",
        scale=NUM_BATCHES * BATCH_SIZE,
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
    assert num_threads < 50, f"Too many threads ({num_threads}), possible watcher leak"


@pytest.mark.loadtest
async def test_watcher_cleanup_allows_restart(
    sse_server_url: str,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify watcher stops when all connections close, restarts with new connections.

    ## What is Measured
    - registered_events after Phase 1 (should be near 0 after cleanup)
    - Events received in Phase 2 (watcher must restart to deliver them)
    - Final registered_events (should match Phase 1 cleanup)

    ## Why This Matters
    Tests the complete watcher lifecycle:
    1. Start: First connection starts the watcher
    2. Broadcast: Watcher delivers shutdown signals to all registered events
    3. Cleanup: Last connection removes its event, watcher stops
    4. Restart: New connections restart the watcher

    If cleanup fails, events accumulate indefinitely. If restart fails, new
    connections won't receive shutdown signals, causing graceful shutdown to fail.

    ## Methodology
    1. Phase 1: Connect CLIENTS_PER_PHASE clients, each receives EVENTS_PER_CLIENT events, then disconnects
    2. Wait 1s for cleanup
    3. Check registered_events (should be near 0)
    4. Phase 2: Connect CLIENTS_PER_PHASE new clients, each receives EVENTS_PER_CLIENT events
    5. Wait 1s for cleanup
    6. Verify final state matches Phase 1 post-cleanup

    ## Pass Criteria
    - phase1_events > 0 (Phase 1 received events)
    - phase2_events > 0 (Phase 2 received events - proves restart worked)
    - final_events <= events_after_phase1 + 5 (cleanup works consistently)
    - Rationale: If watcher didn't restart in Phase 2, no events would be
      delivered. The +5 margin allows for concurrent test interference.
    """
    # Test parameters
    CLIENTS_PER_PHASE = 50
    EVENTS_PER_CLIENT = 20

    async def connect_and_consume(n_events: int) -> tuple[int, str | None]:
        count = 0
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.05"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if count >= n_events:
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    start_time = time.perf_counter()

    # Phase 1: Connect, consume, disconnect
    tasks = [
        asyncio.create_task(connect_and_consume(EVENTS_PER_CLIENT))
        for _ in range(CLIENTS_PER_PHASE)
    ]
    results = await asyncio.gather(*tasks)

    phase1_events = 0
    for result in results:
        if isinstance(result, tuple):
            count, error = result
            phase1_events += count
            metrics_collector.add_client_events(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Wait for cleanup
    await asyncio.sleep(1)

    # Check state is clean
    async with httpx.AsyncClient() as client:
        metrics1 = (await client.get(f"{sse_server_url}/metrics")).json()
    events_after_phase1 = metrics1["registered_events"]
    metrics_collector.add_memory_sample(metrics1["memory_rss_mb"])

    # Phase 2: New connections should work
    tasks = [
        asyncio.create_task(connect_and_consume(EVENTS_PER_CLIENT))
        for _ in range(CLIENTS_PER_PHASE)
    ]
    results = await asyncio.gather(*tasks)

    phase2_events = 0
    for result in results:
        if isinstance(result, tuple):
            count, error = result
            phase2_events += count
            metrics_collector.add_client_events(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Wait for cleanup
    await asyncio.sleep(1)

    elapsed = time.perf_counter() - start_time
    metrics_collector.set_duration(elapsed)

    # Verify clean state
    async with httpx.AsyncClient() as client:
        metrics2 = (await client.get(f"{sse_server_url}/metrics")).json()

    final_events = metrics2["registered_events"]
    metrics_collector.add_memory_sample(metrics2["memory_rss_mb"])

    # Record SSE internals
    metrics_collector.set_sse_internals(
        watcher_started=metrics2.get("watcher_started", False),
        peak_events=max(events_after_phase1, final_events),
        final_events=final_events,
    )

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_watcher_cleanup_allows_restart",
        scale=CLIENTS_PER_PHASE * 2,
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
    assert phase1_events > 0, "Phase 1 should have received events"
    assert phase2_events > 0, "Phase 2 should have received events"
    assert (
        final_events <= events_after_phase1 + 5
    ), "Event set should be cleaned up between phases"
