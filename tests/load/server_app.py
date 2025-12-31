"""
Load test SSE server application.

Provides SSE endpoints and a metrics endpoint for monitoring during load tests.
"""

import asyncio
import os
import time
from typing import AsyncGenerator

import psutil
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sse_starlette import EventSourceResponse
from sse_starlette.sse import _get_shutdown_state


async def metrics(request: Request) -> JSONResponse:
    """Expose server metrics for monitoring during load tests."""
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()

    # Get watcher and event count from thread-local state
    shutdown_state = _get_shutdown_state()

    return JSONResponse(
        {
            "memory_rss_mb": memory_info.rss / 1024 / 1024,
            "memory_vms_mb": memory_info.vms / 1024 / 1024,
            "num_fds": process.num_fds() if hasattr(process, "num_fds") else -1,
            "num_threads": process.num_threads(),
            "connections": len(process.connections()),
            "cpu_percent": process.cpu_percent(),
            "watcher_started": shutdown_state.watcher_started,
            "registered_events": len(shutdown_state.events),
            "uptime_seconds": time.time() - process.create_time(),
        }
    )


async def endless_stream(request: Request) -> EventSourceResponse:
    """High-frequency event stream for load testing."""
    delay = float(request.query_params.get("delay", "0.01"))  # 100 events/sec default

    async def generate() -> AsyncGenerator[dict, None]:
        counter = 0
        while True:
            if await request.is_disconnected():
                break
            yield {"data": f"event-{counter}", "id": str(counter)}
            counter += 1
            await asyncio.sleep(delay)

    return EventSourceResponse(generate())


async def finite_stream(request: Request) -> EventSourceResponse:
    """Finite event stream for testing completion."""
    count = int(request.query_params.get("count", "100"))
    delay = float(request.query_params.get("delay", "0.01"))

    async def generate() -> AsyncGenerator[dict, None]:
        for i in range(count):
            if await request.is_disconnected():
                break
            yield {"data": f"event-{i}", "id": str(i)}
            await asyncio.sleep(delay)

    return EventSourceResponse(generate())


async def slow_stream(request: Request) -> EventSourceResponse:
    """Slow event stream for backpressure testing."""
    delay = float(request.query_params.get("delay", "1.0"))

    async def generate() -> AsyncGenerator[dict, None]:
        counter = 0
        while True:
            if await request.is_disconnected():
                break
            # Generate larger payloads
            payload = "x" * 4096
            yield {"data": payload, "id": str(counter)}
            counter += 1
            await asyncio.sleep(delay)

    return EventSourceResponse(generate())


async def health(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "healthy"})


routes = [
    Route("/sse", endless_stream),
    Route("/sse/finite", finite_stream),
    Route("/sse/slow", slow_stream),
    Route("/metrics", metrics),
    Route("/health", health),
]

app = Starlette(routes=routes)
