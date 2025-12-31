"""
Basic Server-Sent Events (SSE) example with both Starlette and FastAPI.

This example demonstrates:
- Simple number streaming
- Both Starlette and FastAPI implementations
- Proper client disconnection handling

Usage:
    python 01_basic_sse.py

Test with curl:
    # Basic streaming (will receive numbers 1-10 with 1 second intervals)
    curl -N http://localhost:8000/starlette/numbers

    # Endless streaming (press Ctrl+C to stop)
    curl -N http://localhost:8000/fastapi/endless

    # Custom range
    curl -N http://localhost:8000/fastapi/range/5/15
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


# Main Starlette application
starlette_routes = [
    Route("/starlette/numbers", endpoint=starlette_numbers_endpoint),
    Mount("/fastapi", app=fastapi_app),
]

app = Starlette(debug=True, routes=starlette_routes)

if __name__ == "__main__":
    print("Starting SSE server...")
    print("Available endpoints:")
    print("  - http://localhost:8000/starlette/numbers (numbers 1-10)")
    print("  - http://localhost:8000/fastapi/endless (endless stream)")
    print("  - http://localhost:8000/fastapi/range/5/15 (custom range)")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
