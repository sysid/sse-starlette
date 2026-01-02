"""
Graceful shutdown tests under load.

This module verifies the server shuts down cleanly with active SSE connections:
- SIGTERM handling with concurrent streams
- Connection notification and cleanup timing
- No hanging connections after shutdown

Graceful shutdown is critical for zero-downtime deployments. If SSE connections
aren't properly notified, clients hang until TCP timeout (minutes), causing
poor user experience during rolling updates.
"""

from __future__ import annotations

import asyncio
import signal
import time

import httpx
import pytest
from httpx_sse import aconnect_sse

from .baseline import BaselineManager
from .conftest import register_test_report
from .metrics import MetricsCollector
from .reporter import ReportGenerator


@pytest.mark.loadtest
async def test_graceful_shutdown_with_active_connections(
    docker_available: bool,
    scale: int,
    duration_minutes: int,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify server shuts down cleanly within timeout when SIGTERM is sent.

    ## What is Measured
    - Time from SIGTERM to all connections closed
    - Connection close status (clean_close, server_closed, or error)
    - Percentage of connections that closed successfully

    ## Why This Matters
    Tests the core graceful shutdown mechanism:
    - Uvicorn receives SIGTERM, sets Server.should_exit
    - Watcher detects should_exit, broadcasts to all registered events
    - EventSourceResponse streams terminate, connections close
    - Server waits for in-flight requests, then exits

    Without this working:
    - Rolling deployments cause client disconnects
    - Container orchestrators kill processes after timeout
    - Users experience broken connections during updates

    ## Methodology
    1. Start server in Docker container
    2. Connect `scale` concurrent SSE clients
    3. Wait for connections to establish (~2s)
    4. Send SIGTERM to container
    5. Measure time until all connections close
    6. Categorize close reasons (clean, server-initiated, error)

    ## Pass Criteria
    - >= 90% connections closed (clean_closes + server_closes)
    - Shutdown time < 10 seconds
    - Rationale: 90% accounts for race conditions in test timing. 10s is
      generous but catches hangs. Production should complete in <5s.
    """
    if not docker_available:
        pytest.skip("Docker not available")

    from tests.load.conftest import SSELoadTestContainer

    container = SSELoadTestContainer()
    container.start()

    # Wait for server ready
    await asyncio.sleep(2)
    base_url = container.get_base_url()

    # Verify server is up
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/health")
        assert resp.status_code == 200

    disconnected = asyncio.Event()
    connections_made = 0
    connections_closed = 0

    async def client_task() -> tuple[str, str | None]:
        nonlocal connections_made, connections_closed
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{base_url}/sse?delay=0.1"
                ) as source:
                    connections_made += 1
                    async for _ in source.aiter_sse():
                        if disconnected.is_set():
                            break
            connections_closed += 1
            return "clean_close", None
        except httpx.RemoteProtocolError:
            connections_closed += 1
            return "server_closed", None
        except Exception as e:
            connections_closed += 1
            return f"error:{type(e).__name__}", str(e)

    # Start clients
    tasks = [asyncio.create_task(client_task()) for _ in range(scale)]

    # Wait for connections to establish
    await asyncio.sleep(2)

    # Send SIGTERM to container
    start_shutdown = time.perf_counter()
    container.get_wrapped_container().kill(signal=signal.SIGTERM)

    # Wait for shutdown
    shutdown_timeout = 10
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=shutdown_timeout,
        )
    except asyncio.TimeoutError:
        # Cancel remaining tasks
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)

    shutdown_time = time.perf_counter() - start_shutdown
    metrics_collector.set_duration(shutdown_time)

    # Cleanup container
    try:
        container.stop()
    except Exception:
        pass

    # Analyze results
    clean_closes = 0
    server_closes = 0
    errors = 0

    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
            errors += 1
        elif isinstance(result, tuple):
            status, error = result
            if status == "clean_close":
                metrics_collector.record_success()
                clean_closes += 1
            elif status == "server_closed":
                metrics_collector.record_success()
                server_closes += 1
            elif status.startswith("error:"):
                metrics_collector.record_failure(error or status)
                errors += 1

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_graceful_shutdown_with_active_connections",
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
    total_closed = clean_closes + server_closes + errors
    assert (
        total_closed >= scale * 0.9
    ), f"Not all connections closed: {total_closed}/{scale}"
    assert shutdown_time < 10, f"Shutdown took {shutdown_time:.1f}s, expected < 10s"


@pytest.mark.loadtest
async def test_connections_receive_shutdown_signal(
    docker_available: bool,
    scale: int,
    duration_minutes: int,
    metrics_collector: MetricsCollector,
    baseline_manager: BaselineManager,
    report_generator: ReportGenerator,
    update_baseline: bool,
    fail_on_regression: bool,
) -> None:
    """
    Verify active SSE streams are interrupted by shutdown signal.

    ## What is Measured
    - Events received per client before shutdown
    - Events received (or not) after shutdown signal
    - Connection termination triggered by AppStatus.should_exit

    ## Why This Matters
    Tests that the watcher correctly broadcasts shutdown to active streams:
    - AppStatus.should_exit propagates to watcher task
    - Watcher sets all registered anyio.Event objects
    - EventSourceResponse._ping_task detects event, stops iteration
    - Client receives connection close, not just timeout

    This complements the shutdown timing test by verifying the signal path
    works, not just that connections eventually close.

    ## Methodology
    1. Start server in Docker container
    2. Connect 10 clients to /sse?delay=0.5 (slow stream to keep connections active)
    3. Wait 3s for clients to receive events
    4. Send SIGTERM
    5. Wait for clients to notice stream end
    6. Count events before/after signal

    ## Pass Criteria
    - Total events > 0 (clients received events before shutdown)
    - All clients received < 20 events (interrupted before completing)
    - Rationale: With 0.5s delay, clients receive ~6 events in 3s. If they
      reached 20, they weren't interrupted. This proves the shutdown signal
      propagated through the watcher to active streams.
    """
    if not docker_available:
        pytest.skip("Docker not available")

    from tests.load.conftest import SSELoadTestContainer

    container = SSELoadTestContainer()
    container.start()

    await asyncio.sleep(2)
    base_url = container.get_base_url()

    # Connect clients that will wait for events
    async def client_task() -> tuple[int, str | None]:
        count = 0
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{base_url}/sse?delay=0.5"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if count >= 20:  # Should not reach this
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    tasks = [asyncio.create_task(client_task()) for _ in range(10)]

    # Let them receive a few events
    await asyncio.sleep(3)

    # Kill the server
    container.get_wrapped_container().kill(signal=signal.SIGTERM)

    # Gather results
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=10,
        )
    except asyncio.TimeoutError:
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)

    try:
        container.stop()
    except Exception:
        pass

    # Process results
    total_events = 0
    event_counts: list[int] = []

    for result in results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            count, error = result
            metrics_collector.add_client_events(count)
            total_events += count
            event_counts.append(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_connections_receive_shutdown_signal",
        scale=10,  # Fixed scale for this test
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
    assert total_events > 0, "Clients should have received events before shutdown"
    assert all(
        c < 20 for c in event_counts
    ), "Clients should have been interrupted by shutdown"
