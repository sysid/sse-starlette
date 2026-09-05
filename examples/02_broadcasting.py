# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "fastapi",
#   "uvicorn",
# ]
# ///
"""
Queue-based message broadcasting to multiple SSE clients.

This example demonstrates:
- Broadcasting messages to all connected clients via per-client queues
- Async iterator protocol (``__aiter__``/``__anext__``) for custom streams
- Proper client connection/disconnection tracking
- REST API for sending messages to all connected clients

Usage:
    python examples/02_broadcasting.py

Test with curl:
    # Terminal 1: Subscribe to events (keep running)
    curl -N http://localhost:8000/events

    # Terminal 2: Send messages
    curl -X POST http://localhost:8000/send \
         -H "Content-Type: application/json" \
         -d '{"message": "Hello World"}'

    curl -X POST http://localhost:8000/send \
         -H "Content-Type: application/json" \
         -d '{"message": "Alert!", "event": "alert"}'

    # Multiple clients can subscribe
    for i in {1..3}; do
        curl -N http://localhost:8000/events &
    done
"""

import asyncio
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.requests import Request

from sse_starlette import EventSourceResponse, ServerSentEvent


class _ClientDisconnect:
    """Sentinel used to terminate an evicted client's stream."""


_DISCONNECT = _ClientDisconnect()
_QueueItem = ServerSentEvent | _ClientDisconnect


class BroadcastStream:
    """
    Stream that connects a client to a broadcaster for receiving SSE events.

    This class implements the async iterator protocol (__aiter__/__anext__)
    which allows EventSourceResponse to consume it directly.
    """

    def __init__(self, request: Request, broadcaster: "MessageBroadcaster"):
        self.request = request
        self.broadcaster = broadcaster
        self.queue: Optional[asyncio.Queue[_QueueItem]] = None
        self._registered = False

    def __aiter__(self) -> "BroadcastStream":
        """
        Initialize the stream when EventSourceResponse starts consuming it.

        This is called once when the SSE connection begins. We register
        with the broadcaster here rather than in __init__ to ensure
        we only create the queue when actually needed.
        """
        if not self._registered:
            self.queue = self.broadcaster.add_client()
            self._registered = True
        return self

    async def __anext__(self) -> ServerSentEvent:
        """
        Get the next SSE event for this client.

        EventSourceResponse calls this repeatedly to get the stream of events.
        We check for client disconnection and clean up properly when needed.
        """
        try:
            if await self.request.is_disconnected():
                raise StopAsyncIteration

            # Wait for next message from broadcaster
            # This blocks until a message is broadcast to all clients
            assert self.queue is not None
            message = await self.queue.get()
            if isinstance(message, _ClientDisconnect):
                raise StopAsyncIteration
            return message

        except BaseException:
            # BaseException on purpose: asyncio.CancelledError is not an
            # Exception, and cancellation is how EventSourceResponse stops
            # this stream on client disconnect.
            await self._cleanup()
            raise

    async def aclose(self) -> None:
        """
        Close the stream like an async generator would.

        EventSourceResponse calls aclose() on the body iterator when a send
        times out. Without this method a timed-out client stays registered.
        """
        await self._cleanup()

    async def _cleanup(self):
        """
        Explicit cleanup method to remove this client from broadcaster.
        """
        if self._registered and self.queue:
            self.broadcaster.remove_client(self.queue)
            self._registered = False


class MessageBroadcaster:
    """
    Manages broadcasting messages to multiple connected SSE clients.

    Architecture: Each client gets their own asyncio.Queue. When broadcasting,
    we put the same message into all queues simultaneously. This provides:
    - Isolation: slow clients don't affect others
    - Simplicity: no complex pub/sub mechanism needed
    - Backpressure: individual queues can be managed independently
    """

    def __init__(self, max_queue_size: int = 100):
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than zero")
        self._max_queue_size = max_queue_size
        self._clients: List[asyncio.Queue[_QueueItem]] = []

    def add_client(self) -> asyncio.Queue[_QueueItem]:
        """
        Register a new client and return their dedicated message queue.
        """
        client_queue: asyncio.Queue[_QueueItem] = asyncio.Queue(
            maxsize=self._max_queue_size
        )
        self._clients.append(client_queue)
        return client_queue

    def remove_client(self, client_queue: asyncio.Queue[_QueueItem]) -> None:
        """
        Remove a disconnected client's queue.

        Called when client disconnects or stream ends. This prevents
        memory leaks and ensures we don't try to send to dead connections.
        """
        if client_queue in self._clients:
            self._clients.remove(client_queue)

    def disconnect_client(self, client_queue: asyncio.Queue[_QueueItem]) -> None:
        """Evict a slow client and terminate its stream immediately."""
        self.remove_client(client_queue)

        # A full queue cannot accept the disconnect sentinel. Discard buffered
        # events because this client's stream is being terminated anyway.
        while not client_queue.empty():
            client_queue.get_nowait()
        client_queue.put_nowait(_DISCONNECT)

    async def broadcast(self, message: str, event: Optional[str] = None) -> None:
        """
        Send a message to ALL connected clients simultaneously.

        This creates one ServerSentEvent and puts it into every client's queue.
        Each client's BroadcastStream will then yield this event independently.

        Design choice: We use bounded queues and put_nowait() so a slow client
        cannot consume unbounded memory or block delivery to healthy clients.
        A client whose queue fills is disconnected rather than having events
        dropped. Either way it misses events; disconnecting makes the gap
        visible so the client can reconnect and resync. This example sends no
        event ids, so a real application should add ids and honor
        Last-Event-ID to make that resync possible.
        """
        if not self._clients:
            return

        sse_event = ServerSentEvent(data=message, event=event)

        disconnected_clients = []
        for client_queue in self._clients:
            try:
                client_queue.put_nowait(sse_event)
            except asyncio.QueueFull:
                # Mark client for removal if queue is full
                # This prevents slow clients from accumulating messages
                disconnected_clients.append(client_queue)

        for client_queue in disconnected_clients:
            self.disconnect_client(client_queue)

    def create_stream(self, request: Request) -> BroadcastStream:
        """
        Factory method to create a new stream for a client.

        This provides a clean interface and ensures proper initialization
        of the stream with references to both the request and broadcaster.
        """
        return BroadcastStream(request, self)

    @property
    def client_count(self) -> int:
        """Get number of currently connected clients."""
        return len(self._clients)


class MessageRequest(BaseModel):
    """Request body for the broadcast endpoint."""

    message: str
    event: Optional[str] = None


# Global broadcaster instance - shared across all requests
# Design decision: Single global instance allows all clients to receive
# the same messages. In a multi-instance deployment, you'd use Redis or
# similar for message coordination.
broadcaster = MessageBroadcaster()
app = FastAPI()


@app.get("/events")
async def sse_endpoint(request: Request) -> EventSourceResponse:
    """
    SSE endpoint where clients connect to receive broadcasted messages.

    The stream implements async iteration, so EventSourceResponse can
    consume it directly without additional wrapper logic.
    """
    stream = broadcaster.create_stream(request)
    return EventSourceResponse(stream)


@app.post("/send")
async def send_message(message_request: MessageRequest):
    """
    REST endpoint to broadcast a message to all connected SSE clients.
    """
    await broadcaster.broadcast(
        message=message_request.message, event=message_request.event
    )

    return {
        "status": "sent",
        "clients": broadcaster.client_count,
        "message": message_request.message,
    }


@app.get("/status")
async def get_status():
    """Get current broadcaster status."""
    return {"connected_clients": broadcaster.client_count}


if __name__ == "__main__":
    import uvicorn

    print("SSE Broadcasting Server")
    print("Connect:    curl -N http://localhost:8000/events")
    print(
        "Send msg:   curl -X POST http://localhost:8000/send -H 'Content-Type: application/json' -d '{\"message\": \"Hello\"}'"
    )
    print("Status:     curl http://localhost:8000/status")

    uvicorn.run(app, host="127.0.0.1", port=8000)
