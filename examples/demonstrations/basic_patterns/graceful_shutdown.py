# demonstrations/basic_patterns/graceful_shutdown.py
"""
DEMONSTRATION: Graceful Server Shutdown

PURPOSE:
Shows what happens to active SSE connections when server shuts down gracefully
vs when it's killed forcefully.

KEY LEARNING:
- Graceful shutdown allows streams to complete current operations
- Clients receive proper connection close signals
- Cleanup code in generators gets executed

PATTERN:
Using signal handlers and proper async cleanup ensures data integrity.
"""

import asyncio
import signal
import sys
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from sse_starlette import EventSourceResponse


class ShutdownManager:
    """
    Manages graceful shutdown by coordinating with active streams.
    """

    def __init__(self):
        self.shutdown_requested = False
        self.active_streams = set()

    def register_stream(self, stream_id):
        """Register a new active stream."""
        self.active_streams.add(stream_id)
        print(f"📡 Stream {stream_id} started. Active: {len(self.active_streams)}")

    def unregister_stream(self, stream_id):
        """Unregister a completed stream."""
        self.active_streams.discard(stream_id)
        print(f"📡 Stream {stream_id} ended. Active: {len(self.active_streams)}")

    def request_shutdown(self):
        """Request graceful shutdown."""
        print(f"🛑 Shutdown requested. {len(self.active_streams)} streams active.")
        self.shutdown_requested = True


# Global shutdown manager
shutdown_manager = ShutdownManager()


async def long_running_stream(request: Request):
    """
    Stream that demonstrates cleanup during shutdown.
    """
    stream_id = id(request)
    shutdown_manager.register_stream(stream_id)

    try:
        for i in range(1, 20):  # Long-running stream
            # Check for shutdown signal
            if shutdown_manager.shutdown_requested:
                yield {"data": "Server shutting down gracefully..."}
                break

            # Check for client disconnect
            if await request.is_disconnected():
                print(f"🔌 Client disconnected from stream {stream_id}")
                break

            yield {"data": f"Event {i} from stream {stream_id}"}
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        # This happens during graceful shutdown
        print(f"🧹 Stream {stream_id} cancelled during shutdown")
        yield {"data": "Stream cancelled due to shutdown"}
        raise

    finally:
        # Cleanup always happens
        print(f"🧹 Cleaning up stream {stream_id}")
        shutdown_manager.unregister_stream(stream_id)


async def sse_endpoint(request: Request):
    """SSE endpoint with graceful shutdown support."""
    return EventSourceResponse(long_running_stream(request))


# Setup signal handlers for graceful shutdown
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print(f"\n📢 Received signal {signum}. Initiating graceful shutdown...")
    shutdown_manager.request_shutdown()

    # Give streams time to cleanup
    print("⏳ Waiting for active streams to complete...")
    time.sleep(2)

    print("✅ Graceful shutdown complete.")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Kill command

# Test application
app = Starlette(routes=[Route("/events", sse_endpoint)])

if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run this script
    2. Connect with: curl -N http://localhost:8000/events
    3. Press Ctrl+C to trigger graceful shutdown
    4. Observe how active streams are notified and cleaned up

    COMPARE WITH:
    - Send SIGKILL (kill -9) to see forceful termination
    - Notice the difference in cleanup behavior
    """
    import uvicorn
    import time

    print("🚀 Starting graceful shutdown demonstration...")
    print("📋 Instructions:")
    print("   1. Connect with: curl -N http://localhost:8000/events")
    print("   2. Press Ctrl+C to see graceful shutdown")
    print("   3. Compare with kill -9 <pid> for forceful shutdown")
    print()

    uvicorn.run(app, host="localhost", port=8000, log_level="info")
