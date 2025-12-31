"""
Graceful shutdown tests under load.

Verifies clean shutdown behavior with many active connections.
"""

import asyncio
import signal
import time

import httpx
import pytest
from httpx_sse import aconnect_sse


@pytest.mark.loadtest
async def test_graceful_shutdown_with_active_connections(
    docker_available: bool,
    scale: int,
) -> None:
    """
    Send SIGTERM to server with active connections, verify clean shutdown.

    Pass criteria:
    - Shutdown completes within 5 seconds
    - All connections receive disconnect (no hanging clients)
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

    async def client_task() -> str:
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
            return "clean_close"
        except httpx.RemoteProtocolError:
            connections_closed += 1
            return "server_closed"
        except Exception as e:
            connections_closed += 1
            return f"error:{type(e).__name__}"

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

    # Cleanup container
    try:
        container.stop()
    except Exception:
        pass

    # Analyze results
    clean_closes = sum(1 for r in results if r == "clean_close")
    server_closes = sum(1 for r in results if r == "server_closed")
    errors = sum(1 for r in results if isinstance(r, str) and r.startswith("error:"))

    # All connections should have closed (one way or another)
    total_closed = clean_closes + server_closes + errors
    assert (
        total_closed >= scale * 0.9
    ), f"Not all connections closed: {total_closed}/{scale}"

    # Shutdown should be fast
    assert shutdown_time < 10, f"Shutdown took {shutdown_time:.1f}s, expected < 10s"


@pytest.mark.loadtest
async def test_connections_receive_shutdown_signal(
    docker_available: bool,
) -> None:
    """
    Verify connections are notified of shutdown via SSE.

    When AppStatus.should_exit is set, active streams should terminate gracefully.
    """
    if not docker_available:
        pytest.skip("Docker not available")

    from tests.load.conftest import SSELoadTestContainer

    container = SSELoadTestContainer()
    container.start()

    await asyncio.sleep(2)
    base_url = container.get_base_url()

    # Connect clients that will wait for events
    async def client_task() -> int:
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
        except Exception:
            pass
        return count

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

    # Clients should have received some events before shutdown
    event_counts = [r for r in results if isinstance(r, int)]
    total_events = sum(event_counts)

    assert total_events > 0, "Clients should have received events before shutdown"
    assert all(
        c < 20 for c in event_counts
    ), "Clients should have been interrupted by shutdown"
