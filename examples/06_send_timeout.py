# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "uvicorn",
# ]
# ///
"""
Frozen client detection using ``send_timeout``.

This example demonstrates:
- Using ``send_timeout`` to detect clients that stop consuming data
- Automatic cleanup of frozen/suspended connections
- High-throughput streaming with timeout protection

When a client suspends (e.g. Ctrl+Z on curl), the server's send buffer fills up.
After ``send_timeout`` seconds of blocked sends, the connection is dropped.

Usage:
    python examples/06_send_timeout.py

Test with curl:
    # Normal consumption
    curl -N http://localhost:8000/events

    # Simulate frozen client: suspend curl with Ctrl+Z after a few seconds,
    # then watch the server log — it will disconnect after 10s timeout.
    curl -N http://localhost:8000/events
    # Press Ctrl+Z to suspend
"""

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from sse_starlette import EventSourceResponse


async def events(request):
    async def _event_generator():
        try:
            i = 0
            while True:
                i += 1
                if i % 100 == 0:
                    print(f"Sent {i} events")
                yield dict(data={i: " " * 4096})
                await anyio.sleep(0.001)
        finally:
            print("disconnected")

    return EventSourceResponse(_event_generator(), send_timeout=10)


app = Starlette(
    routes=[
        Route("/events", events),
    ],
)

if __name__ == "__main__":
    print("Starting send timeout SSE server...")
    print("Available endpoints:")
    print("  - http://localhost:8000/events (high-throughput stream, 10s send timeout)")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
