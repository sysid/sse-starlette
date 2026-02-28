# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "uvicorn",
# ]
# ///
"""
Cooperative shutdown with farewell events (v3.3.0).

This example demonstrates:
- Using ``shutdown_event`` to let generators detect server shutdown
- Using ``shutdown_grace_period`` to allow farewell events before force-cancel
- Clean generator termination that sends a final event to clients

When the server shuts down (Ctrl+C), the library sets the ``shutdown_event``.
The generator detects this, yields a farewell event, and returns naturally.
If the generator doesn't finish within ``shutdown_grace_period`` seconds,
it is force-cancelled.

Usage:
    python examples/07_cooperative_shutdown.py

Test with curl:
    # Connect and watch events, then press Ctrl+C on the server
    curl -N http://localhost:8000/events

    # You should see a "shutdown" event before the connection closes
"""

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from sse_starlette import EventSourceResponse


async def events(request: Request):
    shutdown_event = anyio.Event()

    async def generate():
        counter = 0
        while not shutdown_event.is_set():
            counter += 1
            yield {"data": f"tick {counter}", "id": str(counter)}
            # Wait 1s or until shutdown is signaled, whichever comes first
            with anyio.move_on_after(1.0):
                await shutdown_event.wait()

        yield {"event": "shutdown", "data": "server is shutting down, goodbye"}

    return EventSourceResponse(
        generate(),
        shutdown_event=shutdown_event,
        shutdown_grace_period=5.0,
    )


app = Starlette(
    routes=[
        Route("/events", events),
    ],
)

if __name__ == "__main__":
    print("Starting cooperative shutdown SSE server...")
    print("Available endpoints:")
    print("  - http://localhost:8000/events (streams ticks, farewell on Ctrl+C)")
    print()
    print("Try: curl -N http://localhost:8000/events")
    print("Then press Ctrl+C on the server to see the shutdown event.")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
