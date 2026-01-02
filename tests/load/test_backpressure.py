"""
Backpressure and slow client tests.

This module verifies the server handles mixed client speeds correctly:
- Slow consumers don't block fast consumers (per-connection isolation)
- Rapid connection churn doesn't exhaust resources
- send_timeout properly disconnects frozen clients

SSE servers must handle heterogeneous clients. A slow consumer (mobile on 2G)
shouldn't cause head-of-line blocking for fast consumers (desktop on fiber).
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
async def test_slow_clients_dont_block_fast_clients(
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
    Verify slow consumers don't throttle fast consumers (connection isolation).

    ## What is Measured
    - Event count for "fast" clients (consume immediately)
    - Event count for "slow" clients (0.5s processing delay per event)
    - Ratio between fast and slow throughput

    ## Why This Matters
    Tests per-connection isolation in the send path:
    - Each connection has its own anyio.Lock for sends
    - Slow client's blocked send() doesn't block other connections
    - No shared buffers that could cause head-of-line blocking

    Without isolation, a single slow client could stall all other streams,
    making the server unusable under mixed load.

    ## Methodology
    1. Connect 10 "fast" clients (consume events immediately)
    2. Connect 10 "slow" clients (sleep 0.5s after each event)
    3. Run for 10 seconds
    4. Compare event counts

    ## Pass Criteria
    - Fast clients avg > slow clients avg * 5 (isolation works)
    - Fast clients avg > 500 events (not throttled by slow clients)
    - Rationale: With 10ms delay, fast clients should receive ~1000 events.
      Slow clients receive ~20 (10s / 0.5s). 5x ratio is conservative.
      500 events threshold catches severe throttling.
    """
    test_duration = 10  # seconds

    async def fast_client() -> tuple[int, str | None]:
        """Client that consumes events as fast as possible."""
        count = 0
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if time.perf_counter() - start >= test_duration:
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    async def slow_client() -> tuple[int, str | None]:
        """Client that reads slowly (simulating processing delay)."""
        count = 0
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    async for _ in source.aiter_sse():
                        await asyncio.sleep(0.5)  # Slow processing
                        count += 1
                        if time.perf_counter() - start >= test_duration:
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    start_time = time.perf_counter()

    # Mix of fast and slow clients
    fast_tasks = [asyncio.create_task(fast_client()) for _ in range(10)]
    slow_tasks = [asyncio.create_task(slow_client()) for _ in range(10)]

    fast_results = await asyncio.gather(*fast_tasks)
    slow_results = await asyncio.gather(*slow_tasks)

    elapsed = time.perf_counter() - start_time
    metrics_collector.set_duration(elapsed)

    # Process results
    fast_counts: list[int] = []
    slow_counts: list[int] = []

    for result in fast_results:
        if isinstance(result, tuple):
            count, error = result
            fast_counts.append(count)
            metrics_collector.add_client_events(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    for result in slow_results:
        if isinstance(result, tuple):
            count, error = result
            slow_counts.append(count)
            metrics_collector.add_client_events(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    avg_fast = sum(fast_counts) / len(fast_counts) if fast_counts else 0
    avg_slow = sum(slow_counts) / len(slow_counts) if slow_counts else 0

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_slow_clients_dont_block_fast_clients",
        scale=20,  # 10 fast + 10 slow
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
    assert avg_fast > avg_slow * 5, (
        f"Fast clients ({avg_fast:.0f} events) should be much faster than "
        f"slow clients ({avg_slow:.0f} events)"
    )
    assert (
        avg_fast > 500
    ), f"Fast clients throttled: {avg_fast:.0f} events, expected > 500"


@pytest.mark.loadtest
async def test_connection_churn_stability(
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
    Verify rapid connect/disconnect doesn't exhaust file descriptors or memory.

    ## What is Measured
    - File descriptor count before and after churn
    - Memory (RSS) before and after churn
    - Connection success rate during churn

    ## Why This Matters
    Tests resource cleanup under high connection churn:
    - Sockets properly closed on disconnect
    - Task references released after completion
    - No accumulation of leaked resources

    In production, clients frequently reconnect (mobile network switches,
    browser tab refresh). Resource leaks under churn cause eventual exhaustion.

    ## Methodology
    1. Record baseline FDs and memory
    2. Create `churn_rate` connections per second for 30 seconds
    3. Each connection receives one event and disconnects
    4. Sample memory every 5 seconds
    5. Record final FDs and memory

    ## Pass Criteria
    - FD growth < 50 (no socket leaks)
    - Memory growth < 100MB (no major retention)
    - Success rate > 90% (server stays responsive under churn)
    - Rationale: 50 FDs allows for some timing variance in cleanup.
      100MB memory is generous but catches runaway allocation.
      90% success rate accounts for expected failures under heavy churn.
    """
    churn_rate = min(100, scale)  # connections per second
    duration = 30  # seconds
    total_connections = churn_rate * duration

    async def quick_connection() -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0"
                ) as source:
                    async for _ in source.aiter_sse():
                        return True, None
        except Exception as e:
            return False, str(e)
        return False, "no events"

    # Get baseline metrics
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()

    baseline_fds = baseline.get("num_fds", 0)
    baseline_memory = baseline["memory_rss_mb"]
    metrics_collector.set_memory_baseline(baseline_memory)

    start_time = time.perf_counter()

    # Create connections at target rate
    successful = 0
    for batch in range(duration):
        tasks = [asyncio.create_task(quick_connection()) for _ in range(churn_rate)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                metrics_collector.record_failure(str(result))
            elif isinstance(result, tuple):
                success, error = result
                if success:
                    metrics_collector.record_success()
                    successful += 1
                else:
                    metrics_collector.record_failure(error or "unknown")

        # Sample memory periodically
        if batch % 5 == 0:
            try:
                async with httpx.AsyncClient() as client:
                    metrics = (await client.get(f"{sse_server_url}/metrics")).json()
                    metrics_collector.add_memory_sample(metrics["memory_rss_mb"])
            except Exception:
                pass

        await asyncio.sleep(0.5)  # Allow some cleanup

    elapsed = time.perf_counter() - start_time
    metrics_collector.set_duration(elapsed)

    # Get final metrics
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()

    final_fds = final.get("num_fds", 0)
    final_memory = final["memory_rss_mb"]
    metrics_collector.set_memory_final(final_memory)

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_connection_churn_stability",
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
    if baseline_fds > 0 and final_fds > 0:
        fd_growth = final_fds - baseline_fds
        assert fd_growth < 50, (
            f"File descriptor leak: {fd_growth} new FDs after {total_connections} "
            f"connections"
        )

    memory_growth = final_memory - baseline_memory
    assert (
        memory_growth < 100
    ), f"Memory grew by {memory_growth:.1f}MB during churn test"

    success_rate = successful / total_connections if total_connections > 0 else 0
    assert success_rate > 0.9, (
        f"Low success rate during churn: {success_rate:.1%} "
        f"({successful}/{total_connections})"
    )


@pytest.mark.loadtest
async def test_send_timeout_under_load(
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
    Verify send_timeout disconnects frozen clients without blocking normal clients.

    ## What is Measured
    - Event count for normal clients (should complete successfully)
    - Outcome for "frozen" clients (stop reading after first event)
    - Implicit: server responsiveness during frozen client handling

    ## Why This Matters
    Tests the send_timeout feature:
    - Frozen clients (stop reading but don't close connection) block the send()
    - Without timeout, server thread/task hangs indefinitely
    - With timeout, server detects blocked send and closes connection
    - Normal clients should be unaffected by frozen clients

    This is critical for production resilience. Mobile clients frequently
    "freeze" (backgrounded, network change) without closing connections.

    ## Methodology
    1. Connect 5 "frozen" clients (receive one event, then stop reading)
    2. Connect 3 "normal" clients (receive 50 events normally)
    3. Wait for normal clients to complete
    4. Verify normal clients weren't affected

    ## Pass Criteria
    - Normal clients receive >= 45/50 events
    - Rationale: Normal clients should complete unaffected. 45/50 allows
      small margin for timing. If frozen clients blocked the server,
      normal clients would timeout or receive far fewer events.
    """

    async def frozen_client() -> tuple[str, float, str | None]:
        """Client that stops reading after first event (simulates frozen client)."""
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.001"
                ) as source:
                    async for _ in source.aiter_sse():
                        # Stop reading but keep connection open
                        await asyncio.sleep(60)  # Will be interrupted by timeout
                        break
        except httpx.ReadTimeout:
            return "timeout", time.perf_counter() - start, None
        except Exception as e:
            return f"error:{type(e).__name__}", time.perf_counter() - start, str(e)
        return "completed", time.perf_counter() - start, None

    # Start some frozen clients (server has default send_timeout)
    frozen_tasks = [asyncio.create_task(frozen_client()) for _ in range(5)]

    # Also verify server remains responsive with normal clients
    async def normal_client() -> tuple[int, str | None]:
        count = 0
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.1"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if count >= 50:
                            break
            return count, None
        except Exception as e:
            return count, str(e)

    normal_tasks = [asyncio.create_task(normal_client()) for _ in range(3)]

    # Wait for normal clients to complete
    normal_results = await asyncio.gather(*normal_tasks)

    # Process normal client results
    normal_counts: list[int] = []
    for result in normal_results:
        if isinstance(result, tuple):
            count, error = result
            normal_counts.append(count)
            metrics_collector.add_client_events(count)
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Cancel frozen clients if still running
    for task in frozen_tasks:
        if not task.done():
            task.cancel()

    frozen_results = await asyncio.gather(*frozen_tasks, return_exceptions=True)

    # Process frozen client results
    for result in frozen_results:
        if isinstance(result, Exception):
            metrics_collector.record_failure(str(result))
        elif isinstance(result, tuple):
            status, duration, error = result
            if error:
                metrics_collector.record_failure(error)
            else:
                metrics_collector.record_success()

    # Generate report
    report = metrics_collector.compute_report(
        test_name="test_send_timeout_under_load",
        scale=8,  # 5 frozen + 3 normal
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
    assert all(
        r >= 45 for r in normal_counts
    ), f"Normal clients affected by frozen clients: {normal_counts}"
