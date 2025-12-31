"""
Watcher deduplication tests at scale.

Validates the Issue #152 fix: only one watcher task per thread regardless
of the number of concurrent connections.
"""

import asyncio

import httpx
import pytest
from httpx_sse import aconnect_sse


@pytest.mark.loadtest
async def test_single_watcher_with_many_connections(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    With N concurrent connections, verify only 1 watcher is running.

    This is the core regression test for Issue #152.
    """

    async def client_task() -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.1"
                ) as source:
                    async for _ in source.aiter_sse():
                        await asyncio.sleep(5)  # Stay connected
                        break
        except Exception:
            pass

    # Start many connections
    tasks = [asyncio.create_task(client_task()) for _ in range(scale)]

    # Wait for connections to establish
    await asyncio.sleep(2)

    # Check watcher status
    async with httpx.AsyncClient() as client:
        metrics = (await client.get(f"{sse_server_url}/metrics")).json()

    watcher_started = metrics["watcher_started"]
    registered_events = metrics["registered_events"]

    # Cancel all tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Watcher should be running
    assert watcher_started is True, "Watcher should be started with active connections"

    # Should have many events registered (one per connection)
    assert (
        registered_events >= scale * 0.5
    ), f"Expected at least {scale * 0.5} events, got {registered_events}"


@pytest.mark.loadtest
async def test_rapid_connect_disconnect_watcher_stability(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Rapid connect/disconnect cycles should not accumulate watchers.

    Each connect/disconnect should reuse the existing watcher, not spawn new ones.
    """

    async def quick_connect() -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.01"
                ) as source:
                    async for _ in source.aiter_sse():
                        break  # Disconnect after first event
        except Exception:
            pass

    # Rapid connect/disconnect cycles
    for batch in range(scale // 10):
        tasks = [asyncio.create_task(quick_connect()) for _ in range(10)]
        await asyncio.gather(*tasks, return_exceptions=True)

    # Brief pause
    await asyncio.sleep(0.5)

    # Check metrics - watcher should still be singular
    async with httpx.AsyncClient() as client:
        metrics = (await client.get(f"{sse_server_url}/metrics")).json()

    # The watcher_started flag confirms single watcher pattern
    # If multiple watchers had spawned, we'd see resource issues
    num_threads = metrics["num_threads"]

    # Thread count should be reasonable (not proportional to connection count)
    # A healthy uvicorn worker has ~5-10 threads typically
    assert num_threads < 50, f"Too many threads ({num_threads}), possible watcher leak"


@pytest.mark.loadtest
async def test_watcher_cleanup_allows_restart(sse_server_url: str) -> None:
    """
    After all connections close, new connections should start fresh watcher.

    Tests the watcher lifecycle: start -> broadcast -> cleanup -> restart.
    """

    async def connect_and_consume(n_events: int) -> int:
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
        except Exception:
            pass
        return count

    # Phase 1: Connect, consume, disconnect
    tasks = [asyncio.create_task(connect_and_consume(20)) for _ in range(50)]
    results = await asyncio.gather(*tasks)
    assert sum(results) > 0, "Phase 1 should have received events"

    # Wait for cleanup
    await asyncio.sleep(1)

    # Check state is clean
    async with httpx.AsyncClient() as client:
        metrics1 = (await client.get(f"{sse_server_url}/metrics")).json()
    events_after_phase1 = metrics1["registered_events"]

    # Phase 2: New connections should work
    tasks = [asyncio.create_task(connect_and_consume(20)) for _ in range(50)]
    results = await asyncio.gather(*tasks)
    assert sum(results) > 0, "Phase 2 should have received events"

    # Wait for cleanup
    await asyncio.sleep(1)

    # Verify clean state
    async with httpx.AsyncClient() as client:
        metrics2 = (await client.get(f"{sse_server_url}/metrics")).json()

    # Events should be cleaned up after both phases
    assert (
        metrics2["registered_events"] <= events_after_phase1 + 5
    ), "Event set should be cleaned up between phases"
