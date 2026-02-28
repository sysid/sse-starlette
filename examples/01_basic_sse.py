# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "fastapi",
#   "uvicorn",
# ]
# ///
"""
Basic Server-Sent Events (SSE) example with both Starlette and FastAPI.

This example demonstrates:
- Finite streaming (numbers 1-10)
- Endless streaming with client disconnect handling
- Conditional data availability (yield only when data exists)
- Both Starlette and FastAPI implementations

Usage:
    python examples/01_basic_sse.py

Test with curl:
    # Finite stream (numbers 1-10, then closes)
    curl -N http://localhost:8000/starlette/numbers

    # Endless stream (press Ctrl+C to stop)
    curl -N http://localhost:8000/fastapi/endless

    # Custom range
    curl -N http://localhost:8000/fastapi/range/5/15

    # Conditional stream (yields one item, then keeps connection open)
    curl -N http://localhost:8000/fastapi/conditional
"""

import asyncio
import logging
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route, Mount

from sse_starlette import EventSourceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_numbers(
    start: int, end: int, delay: float = 1.0
) -> AsyncGenerator[dict, None]:
    """Generate numbered events with configurable range and delay."""
    for number in range(start, end + 1):
        await asyncio.sleep(delay)
        yield {"data": f"Number: {number}"}


async def generate_endless_stream(request: Request) -> AsyncGenerator[dict, None]:
    """Generate endless numbered events with proper cleanup on client disconnect."""
    counter = 0
    try:
        while True:
            counter += 1
            yield {"data": f"Event #{counter}", "id": str(counter)}
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info(f"Client disconnected after receiving {counter} events")
        raise


# Starlette implementation
async def starlette_numbers_endpoint(request: Request) -> EventSourceResponse:
    """Starlette endpoint that streams numbers 1-10."""
    return EventSourceResponse(generate_numbers(1, 10))


# FastAPI implementation
fastapi_app = FastAPI(title="SSE FastAPI Example")


@fastapi_app.get("/endless")
async def fastapi_endless_endpoint(request: Request) -> EventSourceResponse:
    """FastAPI endpoint that streams endless events."""
    return EventSourceResponse(generate_endless_stream(request))


@fastapi_app.get("/range/{start}/{end}")
async def fastapi_range_endpoint(
    request: Request, start: int, end: int
) -> EventSourceResponse:
    """FastAPI endpoint that streams a custom range of numbers."""
    return EventSourceResponse(generate_numbers(start, end))


async def generate_conditional_stream(
    request: Request,
) -> AsyncGenerator[dict, None]:
    """Yield events only when data is available, sleeping between checks.

    This pattern is common in real-world applications where new data
    arrives intermittently (e.g. new chat messages, sensor readings).
    The generator keeps the connection open but only sends events when
    there is something to report.
    """
    has_data = True
    while True:
        if await request.is_disconnected():
            break
        if has_data:
            yield dict(data="new data available")
            has_data = False  # Simulate: data consumed, wait for more
        await asyncio.sleep(0.9)


@fastapi_app.get("/conditional")
async def fastapi_conditional_endpoint(request: Request) -> EventSourceResponse:
    """FastAPI endpoint demonstrating conditional data availability."""
    return EventSourceResponse(generate_conditional_stream(request))


# Main Starlette application
starlette_routes = [
    Route("/starlette/numbers", endpoint=starlette_numbers_endpoint),
    Mount("/fastapi", app=fastapi_app),
]

app = Starlette(debug=True, routes=starlette_routes)

if __name__ == "__main__":
    print("Starting SSE server...")
    print("Available endpoints:")
    print("  - http://localhost:8000/starlette/numbers (finite stream, numbers 1-10)")
    print("  - http://localhost:8000/fastapi/endless (endless stream)")
    print("  - http://localhost:8000/fastapi/range/5/15 (custom range)")
    print(
        "  - http://localhost:8000/fastapi/conditional (yield only when data available)"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
