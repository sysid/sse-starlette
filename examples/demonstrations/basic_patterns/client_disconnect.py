# demonstrations/basic_patterns/client_disconnect.py
"""
DEMONSTRATION: Client Disconnect Detection

PURPOSE:
Shows how server detects when clients disconnect and properly cleans up resources.

KEY LEARNING:
- Server can detect client disconnections using request.is_disconnected()
- Cleanup code runs when clients disconnect unexpectedly
- Resource management is critical for production SSE

PATTERN:
Regular polling for disconnection combined with proper exception handling.
"""

import asyncio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from sse_starlette import EventSourceResponse


class ConnectionTracker:
    """
    Tracks active connections for demonstration purposes.
    In production, this might track database connections, file handles, etc.
    """

    def __init__(self):
        self.connections = {}

    def add_connection(self, connection_id, info):
        self.connections[connection_id] = {
            'start_time': asyncio.get_event_loop().time(),
            'info': info,
            'events_sent': 0
        }
        print(f"➕ Connection {connection_id} added. Total: {len(self.connections)}")

    def update_connection(self, connection_id, events_sent):
        if connection_id in self.connections:
            self.connections[connection_id]['events_sent'] = events_sent

    def remove_connection(self, connection_id, reason="unknown"):
        if connection_id in self.connections:
            conn = self.connections.pop(connection_id)
            duration = asyncio.get_event_loop().time() - conn['start_time']
            print(f"➖ Connection {connection_id} removed ({reason})")
            print(f"   Duration: {duration:.1f}s, Events sent: {conn['events_sent']}")
            print(f"   Active connections: {len(self.connections)}")


# Global connection tracker
tracker = ConnectionTracker()


async def monitored_stream(request: Request):
    """
    Stream that actively monitors for client disconnection.
    """
    connection_id = id(request)
    client_info = f"Client from {request.client}" if request.client else "Unknown client"

    # Register this connection
    tracker.add_connection(connection_id, client_info)

    try:
        events_sent = 0

        for i in range(1, 100):  # Long stream to allow disconnection testing
            # CRITICAL: Check for disconnection before sending each event
            if await request.is_disconnected():
                tracker.remove_connection(connection_id, "client_disconnected")
                print(f"🔌 Client {connection_id} disconnected after {events_sent} events")
                break

            # Send event
            yield {"data": f"Event {i} - {client_info}", "id": str(i)}
            events_sent += 1
            tracker.update_connection(connection_id, events_sent)

            # Longer delay to make disconnection testing easier
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        # Client disconnected via cancellation (e.g., Ctrl+C in curl)
        tracker.remove_connection(connection_id, "stream_cancelled")
        print(f"❌ Stream {connection_id} cancelled")
        raise

    except Exception as e:
        # Unexpected error
        tracker.remove_connection(connection_id, f"error: {e}")
        print(f"💥 Stream {connection_id} failed: {e}")
        raise

    finally:
        # This always runs, ensuring cleanup
        print(f"🧹 Cleanup completed for connection {connection_id}")


async def sse_endpoint(request: Request):
    """SSE endpoint with connection monitoring."""
    return EventSourceResponse(monitored_stream(request))


async def status_endpoint(request: Request):
    """Show current connection status."""
    from starlette.responses import JSONResponse
    return JSONResponse({
        "active_connections": len(tracker.connections),
        "connections": {
            str(conn_id): {
                "duration": asyncio.get_event_loop().time() - conn["start_time"],
                "events_sent": conn["events_sent"],
                "info": conn["info"]
            }
            for conn_id, conn in tracker.connections.items()
        }
    })


# Test application
app = Starlette(routes=[
    Route("/events", sse_endpoint),
    Route("/status", status_endpoint)
])

if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run this script
    2. Open multiple terminals and connect:
       curl -N http://localhost:8000/events
    3. Check status: curl http://localhost:8000/status
    4. Press Ctrl+C in one terminal (client disconnect)
    5. Observe server detection and cleanup
    6. Check status again to see updated connection count

    KEY OBSERVATIONS:
    - Server immediately detects disconnections
    - Cleanup code runs automatically
    - Other connections remain unaffected
    - Resource tracking prevents memory leaks
    """
    import uvicorn

    print("🚀 Starting client disconnect demonstration...")
    print()
    print("📋 Instructions:")
    print("   1. Connect: curl -N http://localhost:8000/events")
    print("   2. Status:  curl http://localhost:8000/status")
    print("   3. Disconnect with Ctrl+C and observe cleanup")
    print()

    uvicorn.run(app, host="localhost", port=8000, log_level="info")
