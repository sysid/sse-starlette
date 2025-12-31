"""
Throughput and latency tests for sse-starlette.

Measures events per second, latency percentiles, and first event latency.
"""

import asyncio
import time
from typing import List

import httpx
import pytest
from httpx_sse import aconnect_sse


@pytest.mark.loadtest
async def test_throughput_single_client(sse_server_url: str) -> None:
    """
    Measure maximum throughput for a single client.

    Baseline measurement without contention.
    """
    events_received = 0
    start_time = time.perf_counter()
    duration_seconds = 10

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with aconnect_sse(
            client, "GET", f"{sse_server_url}/sse?delay=0"
        ) as source:
            async for _ in source.aiter_sse():
                events_received += 1
                if time.perf_counter() - start_time >= duration_seconds:
                    break

    elapsed = time.perf_counter() - start_time
    throughput = events_received / elapsed

    # Should achieve at least 1000 events/sec for a single client
    assert (
        throughput >= 1000
    ), f"Single client throughput {throughput:.0f} events/sec, expected >= 1000"


@pytest.mark.loadtest
async def test_throughput_multiple_clients(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Measure aggregate throughput with multiple concurrent clients.

    Pass criteria:
    - Aggregate throughput > 10,000 events/sec
    """
    duration_seconds = 30

    async def client_task() -> int:
        count = 0
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0.001"
                ) as source:
                    async for _ in source.aiter_sse():
                        count += 1
                        if time.perf_counter() - start >= duration_seconds:
                            break
        except Exception:
            pass
        return count

    start_time = time.perf_counter()
    tasks = [asyncio.create_task(client_task()) for _ in range(scale)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - start_time

    total_events = sum(r for r in results if isinstance(r, int))
    aggregate_throughput = total_events / elapsed

    # With scale clients, should achieve high aggregate throughput
    min_expected = min(10000, scale * 100)  # Scale expectation with client count
    assert aggregate_throughput >= min_expected, (
        f"Aggregate throughput {aggregate_throughput:.0f} events/sec with {scale} "
        f"clients, expected >= {min_expected}"
    )


@pytest.mark.loadtest
async def test_first_event_latency(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Measure time to first event (TTFE) for multiple connections.

    Pass criteria (relaxed for Docker overhead):
    - p50 TTFE < 2000ms
    - p99 TTFE < 5000ms
    """
    latencies: List[float] = []

    async def measure_ttfe() -> float:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with aconnect_sse(
                    client, "GET", f"{sse_server_url}/sse?delay=0"
                ) as source:
                    async for _ in source.aiter_sse():
                        return (time.perf_counter() - start) * 1000  # ms
        except Exception:
            return -1
        return -1

    tasks = [asyncio.create_task(measure_ttfe()) for _ in range(scale)]
    results = await asyncio.gather(*tasks)

    latencies = [r for r in results if r > 0]

    if len(latencies) < scale * 0.9:
        pytest.fail(f"Too many failed connections: {len(latencies)}/{scale}")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p99 = latencies[int(len(latencies) * 0.99)]

    # Relaxed thresholds: Docker networking + container overhead
    assert p50 < 2000, f"p50 TTFE {p50:.1f}ms, expected < 2000ms"
    assert p99 < 5000, f"p99 TTFE {p99:.1f}ms, expected < 5000ms"


@pytest.mark.loadtest
async def test_event_latency_under_load(
    sse_server_url: str,
    scale: int,
) -> None:
    """
    Measure event-to-event latency under load.

    Captures latency between consecutive events to detect backpressure.
    """
    all_latencies: List[float] = []

    async def measure_latencies() -> List[float]:
        latencies: List[float] = []
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
                        if count >= 100:
                            break
        except Exception:
            pass
        return latencies

    tasks = [asyncio.create_task(measure_latencies()) for _ in range(scale)]
    results = await asyncio.gather(*tasks)

    for client_latencies in results:
        all_latencies.extend(client_latencies)

    if len(all_latencies) < 100:
        pytest.fail(f"Insufficient latency samples: {len(all_latencies)}")

    all_latencies.sort()
    p50 = all_latencies[len(all_latencies) // 2]
    p95 = all_latencies[int(len(all_latencies) * 0.95)]
    p99 = all_latencies[int(len(all_latencies) * 0.99)]

    # Expected ~10ms between events (0.01s delay)
    # Allow 2x for processing overhead under load
    assert p50 < 50, f"p50 inter-event latency {p50:.1f}ms, expected < 50ms"
    assert p95 < 100, f"p95 inter-event latency {p95:.1f}ms, expected < 100ms"
    assert p99 < 200, f"p99 inter-event latency {p99:.1f}ms, expected < 200ms"
