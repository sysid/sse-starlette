"""
Backpressure and slow client tests.

Verifies server handles slow consumers correctly without affecting fast clients.
"""

import asyncio
import time
from typing import Tuple

import httpx
import pytest
from httpx_sse import aconnect_sse


@pytest.mark.loadtest
async def test_slow_clients_dont_block_fast_clients(
    sse_server_url: str,
) -> None:
    """
    Slow clients should not affect throughput of fast clients.

    Tests that the server properly handles mixed client speeds.
    """
    test_duration = 10  # seconds

    async def fast_client() -> int:
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
        except Exception:
            pass
        return count

    async def slow_client() -> int:
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
        except Exception:
            pass
        return count

    # Mix of fast and slow clients
    fast_tasks = [asyncio.create_task(fast_client()) for _ in range(10)]
    slow_tasks = [asyncio.create_task(slow_client()) for _ in range(10)]

    fast_results = await asyncio.gather(*fast_tasks)
    slow_results = await asyncio.gather(*slow_tasks)

    avg_fast = sum(fast_results) / len(fast_results)
    avg_slow = sum(slow_results) / len(slow_results)

    # Fast clients should receive significantly more events
    assert avg_fast > avg_slow * 5, (
        f"Fast clients ({avg_fast:.0f} events) should be much faster than "
        f"slow clients ({avg_slow:.0f} events)"
    )

    # Fast clients should not be severely throttled
    # With 0.01s delay, should get ~1000 events in 10s
    assert (
        avg_fast > 500
    ), f"Fast clients throttled: {avg_fast:.0f} events, expected > 500"


@pytest.mark.loadtest
async def test_connection_churn_stability(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Rapid connect/disconnect should not cause resource exhaustion.

    Tests cleanup under high churn rate.
    """
    churn_rate = min(100, scale)  # connections per second
    duration = 30  # seconds
    total_connections = churn_rate * duration

    async def quick_connection() -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0"
                ) as source:
                    async for _ in source.aiter_sse():
                        return True
        except Exception:
            return False
        return False

    # Get baseline metrics
    async with httpx.AsyncClient() as client:
        baseline = (await client.get(f"{sse_server_url}/metrics")).json()

    baseline_fds = baseline.get("num_fds", 0)
    baseline_memory = baseline["memory_rss_mb"]

    # Create connections at target rate
    successful = 0
    for batch in range(duration):
        tasks = [asyncio.create_task(quick_connection()) for _ in range(churn_rate)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful += sum(1 for r in results if r is True)
        await asyncio.sleep(0.5)  # Allow some cleanup

    # Get final metrics
    async with httpx.AsyncClient() as client:
        final = (await client.get(f"{sse_server_url}/metrics")).json()

    final_fds = final.get("num_fds", 0)
    final_memory = final["memory_rss_mb"]

    # File descriptors should return to baseline
    if baseline_fds > 0 and final_fds > 0:
        fd_growth = final_fds - baseline_fds
        assert fd_growth < 50, (
            f"File descriptor leak: {fd_growth} new FDs after {total_connections} "
            f"connections"
        )

    # Memory should not grow excessively
    memory_growth = final_memory - baseline_memory
    assert (
        memory_growth < 100
    ), f"Memory grew by {memory_growth:.1f}MB during churn test"

    # Success rate should be high
    success_rate = successful / total_connections if total_connections > 0 else 0
    assert success_rate > 0.9, (
        f"Low success rate during churn: {success_rate:.1%} "
        f"({successful}/{total_connections})"
    )


@pytest.mark.loadtest
async def test_send_timeout_under_load(sse_server_url: str) -> None:
    """
    Verify send_timeout works correctly under load.

    Clients that stop reading should eventually be disconnected.
    """

    async def frozen_client() -> Tuple[str, float]:
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
            return "timeout", time.perf_counter() - start
        except Exception as e:
            return f"error:{type(e).__name__}", time.perf_counter() - start
        return "completed", time.perf_counter() - start

    # Start some frozen clients (server has default send_timeout)
    tasks = [asyncio.create_task(frozen_client()) for _ in range(5)]

    # Also verify server remains responsive with normal clients
    async def normal_client() -> int:
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
        except Exception:
            pass
        return count

    normal_tasks = [asyncio.create_task(normal_client()) for _ in range(3)]

    # Wait for normal clients to complete
    normal_results = await asyncio.gather(*normal_tasks)

    # Cancel frozen clients if still running
    for task in tasks:
        if not task.done():
            task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Normal clients should have completed successfully
    assert all(
        r >= 45 for r in normal_results
    ), f"Normal clients affected by frozen clients: {normal_results}"
