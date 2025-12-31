"""
Memory stability tests for sse-starlette under load.

Verifies no memory leaks during sustained SSE streaming with many concurrent connections.
"""

import asyncio
import statistics
from typing import List

import httpx
import pytest
from httpx_sse import aconnect_sse


@pytest.mark.loadtest
async def test_memory_stability_under_load(
    sse_server_url: str,
    scale: int,
    duration_minutes: int,
) -> None:
    """
    Connect many clients, stream for duration, verify memory is stable.

    Pass criteria:
    - Memory growth < 50MB over test duration
    - No unbounded growth trend (linear regression slope < 0.1 MB/sec)
    """
    events_per_client = duration_minutes * 60 * 10  # 10 events/sec

    async def client_task(client_id: int) -> int:
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
        except Exception:
            pass  # Connection errors during shutdown are expected
        return events_received

    # Get baseline memory
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_memory = baseline["memory_rss_mb"]

    # Start all clients
    tasks = [asyncio.create_task(client_task(i)) for i in range(scale)]

    # Sample memory periodically
    memory_samples: List[float] = []
    sample_interval = max(10, duration_minutes * 6)  # At least 10 samples

    for _ in range(sample_interval):
        await asyncio.sleep(duration_minutes * 60 / sample_interval)
        try:
            async with httpx.AsyncClient() as client:
                metrics = (await client.get(f"{sse_server_url}/metrics")).json()
                memory_samples.append(metrics["memory_rss_mb"])
        except Exception:
            pass  # Server might be under heavy load

    # Wait for all clients to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)
    completed = sum(1 for r in results if isinstance(r, int))

    # Get final memory
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_memory = final["memory_rss_mb"]

    # Calculate memory growth
    max_memory = max(memory_samples) if memory_samples else final_memory
    memory_growth = max_memory - baseline_memory

    # Calculate growth trend (simple linear regression slope)
    if len(memory_samples) >= 2:
        x_mean = len(memory_samples) / 2
        y_mean = statistics.mean(memory_samples)
        numerator = sum(
            (i - x_mean) * (y - y_mean) for i, y in enumerate(memory_samples)
        )
        denominator = sum((i - x_mean) ** 2 for i in range(len(memory_samples)))
        slope = numerator / denominator if denominator else 0
        # Convert to MB/sec
        sample_interval_sec = duration_minutes * 60 / len(memory_samples)
        slope_per_sec = slope / sample_interval_sec
    else:
        slope_per_sec = 0

    # Assert criteria
    assert (
        completed >= scale * 0.9
    ), f"Too many failed connections: {completed}/{scale} completed"
    assert memory_growth < 50, (
        f"Memory grew by {memory_growth:.1f}MB (baseline: {baseline_memory:.1f}MB, "
        f"max: {max_memory:.1f}MB), expected < 50MB"
    )
    assert (
        slope_per_sec < 0.1
    ), f"Memory growth trend {slope_per_sec:.3f} MB/sec, expected < 0.1 MB/sec"


@pytest.mark.loadtest
async def test_memory_returns_to_baseline_after_disconnect(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Connect many clients, disconnect all, verify memory returns near baseline.

    Pass criteria:
    - Memory within 20% of baseline after all connections close
    """

    async def client_task(client_id: int) -> None:
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
        except Exception:
            pass

    # Get baseline
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_memory = baseline["memory_rss_mb"]

    # Connect and disconnect clients in batches
    batch_size = min(100, scale)
    for batch_start in range(0, scale, batch_size):
        batch_end = min(batch_start + batch_size, scale)
        tasks = [
            asyncio.create_task(client_task(i)) for i in range(batch_start, batch_end)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # Wait for cleanup
    await asyncio.sleep(2)

    # Check memory returned to near baseline
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_memory = final["memory_rss_mb"]

    # Allow 20% growth from baseline (some overhead is expected)
    max_allowed = baseline_memory * 1.2
    assert final_memory <= max_allowed, (
        f"Memory did not return to baseline: {final_memory:.1f}MB "
        f"(baseline: {baseline_memory:.1f}MB, max allowed: {max_allowed:.1f}MB)"
    )


@pytest.mark.loadtest
async def test_event_set_cleanup(sse_server_url: str, scale: int) -> None:
    """
    Verify the internal event set empties after connections close.

    This tests the Issue #152 fix - events should be properly removed
    from the thread-local state when connections close.
    """

    connected = asyncio.Event()
    connection_count = 0

    async def client_task() -> None:
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
        except Exception:
            pass

    # Get baseline event count
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()
    baseline_events = baseline["registered_events"]

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

    # Wait for all to complete
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(2)  # Allow cleanup time

    # Check events cleaned up
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()
    final_events = final["registered_events"]

    # Events should have been registered during peak (relaxed threshold)
    assert peak_events >= scale * 0.2, (
        f"Expected at least {scale * 0.2} events registered during peak, "
        f"got {peak_events}"
    )

    # Events should be cleaned up after
    assert final_events <= baseline_events + 10, (
        f"Event set not cleaned up: {final_events} events remaining "
        f"(baseline: {baseline_events})"
    )
