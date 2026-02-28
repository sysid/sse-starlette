# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "fastapi",
#   "uvicorn",
# ]
# ///
"""
Advanced SSE features: custom ping, error handling, separators, and headers.

This example demonstrates:
- Custom ping messages and intervals
- Error handling within streams
- Different line separators
- Background tasks
- Cache control headers for proxies

Usage:
    python examples/04_advanced_features.py

Test with curl:
    # Stream with custom ping (every 3 seconds)
    curl -N http://localhost:8000/custom-ping

    # Stream with error simulation
    curl -N http://localhost:8000/error-demo

    # Stream with send timeout protection
    curl -N http://localhost:8000/timeout-protected

    # Stream with custom separators (notice different line endings)
    curl -N http://localhost:8000/custom-separator

    # Stream with proxy-friendly caching headers
    curl -N http://localhost:8000/proxy-friendly
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from sse_starlette import EventSourceResponse, ServerSentEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SSE Advanced Features")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def create_custom_ping() -> ServerSentEvent:
    """Create a custom ping message that's invisible to the client.
    Because it is sent as a comment.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    return ServerSentEvent(comment=f"invisible ping at\r\n{timestamp}")


async def stream_with_custom_ping() -> AsyncGenerator[dict, None]:
    """Stream data with custom ping configuration."""
    for i in range(1, 11):
        yield {
            "data": f"Message {i} with custom (invisible) ping",
            "id": str(i),
            "event": "custom",
        }
        await asyncio.sleep(2)


async def stream_with_error_handling(request: Request) -> AsyncGenerator[dict, None]:
    """Stream that demonstrates error handling within the generator.

    The error message can be processed on the client-side to handle the error gracefully.
    Note the use of return after yielding the error message.
    This will stop the generator from continuing after an error occurs.
    """
    for i in range(1, 21):
        try:
            # Simulate random errors
            if i == 3:
                raise ValueError("Simulated processing error")
            elif i == 6:
                raise ConnectionError("Simulated connection issue")

            yield {
                "data": f"Successfully processed item {i}",
                "id": str(i),
                "event": "success",
            }
            await asyncio.sleep(0.8)

        except ValueError as e:
            logger.warning(f"Processing error: {e}")
            yield {
                "data": f"Error: {str(e)}. Continuing with next items...",
                "event": "error",
            }
        except ConnectionError as e:
            logger.error(f"Connection error: {e}")
            yield {
                "data": "Connection error occurred. Stream ending.",
                "event": "fatal_error",
            }
            return

        except Exception as e:
            # raise e
            logger.error(f"Unexpected error: {e}")
            yield {"data": "Unexpected error. Stream ending.", "event": "fatal_error"}


async def stream_with_custom_separator() -> AsyncGenerator[dict, None]:
    """Stream demonstrating custom line separators."""
    messages = [
        "First line\nwith newlines\ninside",
        "Second message",
        "Third line\r\nwith CRLF",
        "Final message",
    ]

    for i, message in enumerate(messages, 1):
        yield {"data": message, "id": str(i), "event": "multiline"}
        await asyncio.sleep(1)


def background_cleanup_task():
    """Background task that runs after SSE stream completes."""
    logger.info("Background cleanup task executed")


@app.get("/custom-ping")
async def custom_ping_endpoint() -> EventSourceResponse:
    """Endpoint with custom ping message and interval.
    This examples demonstrates how to use a comment as a ping instead of sending a dedicated event type 'ping'.
    """
    return EventSourceResponse(
        stream_with_custom_ping(),
        ping=3,  # Ping every 3 seconds
        ping_message_factory=create_custom_ping,
    )


@app.get("/error-demo")
async def error_demo_endpoint(request: Request) -> EventSourceResponse:
    """Endpoint demonstrating error handling."""
    return EventSourceResponse(stream_with_error_handling(request), ping=5)


@app.get("/custom-separator")
async def custom_separator_endpoint() -> EventSourceResponse:
    """Endpoint using custom line separators."""
    return EventSourceResponse(
        stream_with_custom_separator(),
        sep="\n",  # Use LF instead of CRLF
        ping=5,
    )


@app.get("/proxy-friendly")
async def proxy_friendly_endpoint() -> EventSourceResponse:
    """Endpoint with headers optimized for proxy caching."""
    return EventSourceResponse(
        stream_with_custom_ping(),
        headers={
            "Cache-Control": "public, max-age=29",  # Allow proxy caching
            "X-Custom-Header": "proxy-optimized",
        },
        background=BackgroundTask(background_cleanup_task),
        ping=5,
    )


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "features": [
            "custom_ping",
            "error_handling",
            "custom_separators",
            "proxy_friendly",
        ],
    }


if __name__ == "__main__":
    print("Starting SSE advanced features server...")
    print("Available endpoints:")
    print("  - GET http://localhost:8000/custom-ping (custom ping every 3s)")
    print("  - GET http://localhost:8000/error-demo (error handling demo)")
    print("  - GET http://localhost:8000/custom-separator (custom line separators)")
    print("  - GET http://localhost:8000/proxy-friendly (proxy-optimized headers)")
    print("  - GET http://localhost:8000/health (health check)")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
