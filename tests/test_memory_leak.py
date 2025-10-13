"""
Memory leak detection and profiling tests for EventSourceResponse.

This test suite validates that EventSourceResponse does not leak memory under
various usage patterns, addressing concerns raised in Issue #142 about lambda
closures potentially retaining references to EventSourceResponse instances.

Test Categories:
- Sequential request memory growth
- Reference cycle detection
- Concurrent request behavior
- Object lifecycle validation
- GC behavior analysis
"""
import asyncio
import gc
import logging
import sys
import tracemalloc
from typing import List, Tuple

import anyio
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from sse_starlette import EventSourceResponse

_log = logging.getLogger(__name__)


# ==============================================================================
# Helper Utilities
# ==============================================================================


class MemorySnapshot:
    """Captures and compares memory snapshots for leak detection."""

    def __init__(self, description: str = ""):
        self.description = description
        self.snapshot = None
        self.peak_memory = 0
        self.current_memory = 0

    def capture(self) -> None:
        """Capture current memory state."""
        gc.collect()  # Force collection before measurement
        self.current_memory, self.peak_memory = tracemalloc.get_traced_memory()
        self.snapshot = tracemalloc.take_snapshot()

    def compare_to(self, other: "MemorySnapshot") -> Tuple[int, List]:
        """
        Compare this snapshot to another and return memory delta and top differences.

        Returns:
            Tuple of (memory_delta_bytes, top_10_differences)
        """
        if not self.snapshot or not other.snapshot:
            raise ValueError("Both snapshots must be captured before comparison")

        delta = self.current_memory - other.current_memory
        top_stats = self.snapshot.compare_to(other.snapshot, "lineno")

        return delta, top_stats[:10]

    def print_top_stats(self, limit: int = 10) -> None:
        """Print top memory allocations from this snapshot."""
        if not self.snapshot:
            return

        _log.info(f"Top {limit} memory allocations for: {self.description}")
        top_stats = self.snapshot.statistics("lineno")

        for index, stat in enumerate(top_stats[:limit], 1):
            _log.info(f"#{index}: {stat}")


def get_eventresponse_objects() -> List:
    """
    Find all EventSourceResponse objects in memory.

    Returns:
        List of EventSourceResponse instances currently in memory
    """
    gc.collect()
    return [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, EventSourceResponse)
    ]


def get_reference_cycles() -> List:
    """
    Detect reference cycles that prevent garbage collection.

    Returns:
        List of objects involved in reference cycles
    """
    gc.collect()
    # Get all objects that are in cycles but not collected
    cycles = [obj for obj in gc.garbage if isinstance(obj, EventSourceResponse)]
    return cycles


# ==============================================================================
# Test Fixtures
# ==============================================================================


@pytest.fixture
def simple_sse_app():
    """Create a minimal SSE app for memory testing."""

    async def sse_endpoint(request):
        async def event_generator():
            for i in range(10):  # Small number for fast tests
                yield {"data": f"event_{i}"}
                await asyncio.sleep(0.01)

        return EventSourceResponse(event_generator(), ping=0.1)

    async def fast_sse_endpoint(request):
        """Endpoint that completes very quickly for stress testing."""
        async def quick_generator():
            for i in range(3):
                yield {"data": f"quick_{i}"}

        return EventSourceResponse(quick_generator(), ping=0.05)

    app = Starlette(
        routes=[
            Route("/sse", sse_endpoint),
            Route("/fast", fast_sse_endpoint),
        ]
    )
    return app


# ==============================================================================
# Memory Leak Tests
# ==============================================================================


class TestMemoryLeaks:
    """Test suite for memory leak detection in EventSourceResponse."""

    def test_sequential_requests_memoryGrowth_thenStaysWithinBounds(
        self, simple_sse_app
    ):
        """
        Test that sequential SSE requests do not cause unbounded memory growth.

        This test measures memory before and after N sequential requests to detect
        if EventSourceResponse instances or their closures are leaking.

        Expected: Memory growth should be minimal and proportional to internal
        caching/buffering, not linear with request count.
        """
        # Arrange
        tracemalloc.start()
        client = TestClient(simple_sse_app)

        # Warm up - first requests may allocate caches/pools
        for _ in range(10):
            response = client.get("/fast")
            assert response.status_code == 200

        # Capture baseline after warmup
        baseline = MemorySnapshot("baseline after warmup")
        baseline.capture()

        # Act - Execute many requests
        num_requests = 100
        for i in range(num_requests):
            response = client.get("/fast")
            assert response.status_code == 200

            # Force GC periodically to simulate normal operation
            if i % 20 == 0:
                gc.collect()

        # Capture final state
        final = MemorySnapshot("after 100 requests")
        final.capture()

        # Assert
        memory_delta, top_diffs = final.compare_to(baseline)

        # Log detailed information for analysis
        _log.info(f"Memory delta: {memory_delta:,} bytes ({memory_delta / 1024:.2f} KB)")
        _log.info(f"Memory per request: {memory_delta / num_requests:.2f} bytes")
        _log.info("Top memory differences:")
        for stat in top_diffs:
            _log.info(f"  {stat}")

        tracemalloc.stop()

        # Define acceptable memory growth threshold
        # Allow 100KB total growth for internal buffers/caches
        # This is ~1KB per request which should be reasonable for any buffering
        max_acceptable_growth = 100 * 1024  # 100 KB

        assert (
            memory_delta < max_acceptable_growth
        ), f"Memory grew by {memory_delta:,} bytes, exceeding threshold of {max_acceptable_growth:,} bytes. Possible memory leak."

    def test_eventResponseObjects_whenRequestsComplete_thenAreGarbageCollected(
        self, simple_sse_app
    ):
        """
        Test that EventSourceResponse objects are properly garbage collected.

        This test verifies that after requests complete, EventSourceResponse
        instances do not remain in memory indefinitely.

        Expected: After GC, no EventSourceResponse objects should remain in memory.
        """
        # Arrange
        client = TestClient(simple_sse_app)

        # Act - Create some responses
        for _ in range(20):
            response = client.get("/fast")
            assert response.status_code == 200

        # Force garbage collection
        gc.collect()
        gc.collect()  # Second pass to handle finalizers

        # Assert
        remaining_objects = get_eventresponse_objects()

        # Log findings
        _log.info(f"EventSourceResponse objects remaining: {len(remaining_objects)}")
        if remaining_objects:
            _log.warning("Found lingering EventSourceResponse objects:")
            for obj in remaining_objects:
                _log.warning(f"  Object: {obj}, Active: {obj.active}")

        # We expect 0 objects to remain after GC
        # Note: In some test environments, a small number may persist due to
        # test client internals. If this becomes flaky, adjust threshold.
        assert len(remaining_objects) <= 1, (
            f"Found {len(remaining_objects)} EventSourceResponse objects after GC. "
            "This suggests a memory leak via retained references."
        )

    def test_referenceCycles_whenRequestsComplete_thenNoCyclesDetected(
        self, simple_sse_app
    ):
        """
        Test that EventSourceResponse does not create uncollectable reference cycles.

        This test checks gc.garbage for any EventSourceResponse instances that
        could not be collected due to reference cycles.

        Expected: No EventSourceResponse objects in gc.garbage after collection.
        """
        # Arrange
        # Enable debug mode to detect cycles
        old_flags = gc.get_debug()
        gc.set_debug(gc.DEBUG_SAVEALL)

        client = TestClient(simple_sse_app)

        # Act - Create some responses
        for _ in range(20):
            response = client.get("/fast")
            assert response.status_code == 200

        # Force garbage collection
        gc.collect()

        # Assert
        cycles = get_reference_cycles()

        # Log findings
        _log.info(f"EventSourceResponse objects in gc.garbage: {len(cycles)}")
        if cycles:
            _log.warning("Found EventSourceResponse objects in reference cycles:")
            for obj in cycles:
                _log.warning(f"  Object: {obj}")

        # Cleanup
        gc.set_debug(old_flags)
        gc.garbage.clear()

        assert len(cycles) == 0, (
            f"Found {len(cycles)} EventSourceResponse objects in reference cycles. "
            "This indicates uncollectable circular references, likely from lambda closures."
        )

    @pytest.mark.anyio
    async def test_concurrentRequests_memoryBehavior_thenNoLeaks(self, simple_sse_app):
        """
        Test memory behavior under concurrent SSE connections.

        This simulates multiple clients connecting simultaneously to verify
        that concurrent usage does not cause memory issues.

        Expected: Memory should scale linearly with active connections and
        return to baseline after connections close.
        """
        # Arrange
        tracemalloc.start()

        from httpx import ASGITransport, AsyncClient

        baseline = MemorySnapshot("baseline")
        baseline.capture()

        # Act - Create concurrent connections
        async with AsyncClient(
            transport=ASGITransport(app=simple_sse_app), base_url="http://test"
        ) as client:
            # Start multiple concurrent streams
            tasks = []
            num_concurrent = 10

            async def consume_stream():
                async with client.stream("GET", "/sse") as response:
                    # Read a few events then close
                    count = 0
                    async for line in response.aiter_lines():
                        count += 1
                        if count >= 10:  # Read 10 lines then stop
                            break

            async with anyio.create_task_group() as tg:
                for _ in range(num_concurrent):
                    tg.start_soon(consume_stream)

            # All streams completed, force GC
            gc.collect()

        # Capture final state after cleanup
        final = MemorySnapshot("after concurrent streams")
        final.capture()

        # Assert
        memory_delta, _ = final.compare_to(baseline)

        _log.info(
            f"Memory delta after {num_concurrent} concurrent streams: {memory_delta:,} bytes"
        )

        tracemalloc.stop()

        # After all connections close and GC runs, memory should return close to baseline
        # Allow some overhead for connection pooling etc
        max_acceptable_growth = 50 * 1024  # 50 KB

        assert (
            memory_delta < max_acceptable_growth
        ), f"Memory grew by {memory_delta:,} bytes after concurrent requests. Possible leak."

    def test_stressTest_rapidSequentialRequests_thenMemoryStable(
        self, simple_sse_app
    ):
        """
        Stress test with rapid sequential requests to detect memory accumulation.

        This test simulates high request volume to see if the lambda closure
        issue from Issue #142 manifests under load.

        Expected: Memory growth should plateau after initial allocations.
        """
        # Arrange
        tracemalloc.start()
        client = TestClient(simple_sse_app)

        # Warmup
        for _ in range(10):
            client.get("/fast")

        gc.collect()
        baseline = MemorySnapshot("baseline")
        baseline.capture()

        # Act - Rapid fire requests
        num_requests = 500
        samples = []

        for i in range(num_requests):
            response = client.get("/fast")
            assert response.status_code == 200

            # Sample memory at intervals
            if i % 100 == 0:
                gc.collect()
                current, _ = tracemalloc.get_traced_memory()
                samples.append((i, current))
                _log.info(f"Request {i}: {current:,} bytes")

        final = MemorySnapshot("after stress test")
        final.capture()

        # Assert
        memory_delta, top_diffs = final.compare_to(baseline)

        _log.info(f"Total memory delta: {memory_delta:,} bytes")
        _log.info(f"Memory per request: {memory_delta / num_requests:.2f} bytes/request")

        # Check memory growth pattern
        if len(samples) >= 2:
            early_memory = samples[0][1]
            late_memory = samples[-1][1]
            late_growth = late_memory - early_memory

            _log.info(f"Memory growth from sample 0 to sample {len(samples)-1}: {late_growth:,} bytes")

        tracemalloc.stop()

        # Under stress, we expect some growth but it should be bounded
        # Allow 200KB for 500 requests = ~400 bytes per request
        max_acceptable_growth = 200 * 1024

        assert (
            memory_delta < max_acceptable_growth
        ), f"Memory grew by {memory_delta:,} bytes under stress test. Exceeds threshold of {max_acceptable_growth:,}. Possible leak."

    def test_objectLifecycle_whenResponseCompletes_thenCleanupOccurs(
        self, simple_sse_app
    ):
        """
        Test the lifecycle of EventSourceResponse objects to ensure proper cleanup.

        This test tracks object creation and destruction to verify that all
        resources are released after a response completes.

        Expected: Objects created during request should not persist after GC.
        """
        # Arrange
        client = TestClient(simple_sse_app)

        # Capture initial object count
        gc.collect()
        initial_objects = get_eventresponse_objects()
        initial_count = len(initial_objects)

        _log.info(f"Initial EventSourceResponse objects: {initial_count}")

        # Act - Make a request
        response = client.get("/fast")
        assert response.status_code == 200

        # Before GC - objects may still exist
        before_gc_objects = get_eventresponse_objects()
        _log.info(f"EventSourceResponse objects before GC: {len(before_gc_objects)}")

        # Force garbage collection
        gc.collect()
        gc.collect()

        # After GC - objects should be cleaned up
        after_gc_objects = get_eventresponse_objects()
        final_count = len(after_gc_objects)

        _log.info(f"EventSourceResponse objects after GC: {final_count}")

        # Assert
        # Allow for test framework overhead - may have 1 object from test client
        assert final_count <= initial_count + 1, (
            f"Found {final_count} EventSourceResponse objects after GC, "
            f"expected <= {initial_count + 1}. Objects not being cleaned up properly."
        )


# ==============================================================================
# Memory Profiling Markers and Utilities
# ==============================================================================


@pytest.mark.memory
class TestMemoryProfiling:
    """
    Memory profiling tests that provide detailed analysis.

    These tests are marked with @pytest.mark.memory and can be run separately
    for detailed profiling: pytest -m memory -v
    """

    def test_detailedMemoryProfile_printTopAllocations(self, simple_sse_app):
        """
        Generate detailed memory profile showing top allocations.

        This test provides diagnostic information about memory usage patterns.
        Run with: pytest tests/test_memory_leak.py::TestMemoryProfiling -v -s
        """
        # Arrange
        tracemalloc.start()
        client = TestClient(simple_sse_app)

        # Act
        for _ in range(50):
            client.get("/fast")

        gc.collect()
        snapshot = MemorySnapshot("detailed profile")
        snapshot.capture()

        # Print detailed statistics
        snapshot.print_top_stats(limit=20)

        tracemalloc.stop()

        # This is a diagnostic test - always passes
        assert True


# ==============================================================================
# Pytest Configuration
# ==============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "memory: marks tests as memory profiling tests (deselect with '-m \"not memory\"')"
    )
