"""
- Queue-based message broadcasting to multiple SSE clients
- Clean Stream abstraction that implements async iterator protocol
- Proper client connection/disconnection handling
- REST API for sending messages to all connected clients

Usage:
    python 02_message_broadcasting.py

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


class BroadcastStream:
    """
    Stream that connects a client to a broadcaster for receiving SSE events.

    This class implements the async iterator protocol (__aiter__/__anext__)
    which allows EventSourceResponse to consume it directly.
    """

    def __init__(self, request: Request, broadcaster: "MessageBroadcaster"):
        self.request = request
        self.broadcaster = broadcaster
        self.queue: Optional[asyncio.Queue] = None
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
                await self._cleanup()
                raise StopAsyncIteration

            # Wait for next message from broadcaster
            # This blocks until a message is broadcast to all clients
            message = await self.queue.get()
            return message

        except Exception:
            await self._cleanup()
            raise

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

    def __init__(self):
        self._clients: List[asyncio.Queue] = []

    def add_client(self) -> asyncio.Queue:
        """
        Register a new client and return their dedicated message queue.
        """
        client_queue = asyncio.Queue()
        self._clients.append(client_queue)
        return client_queue

    def remove_client(self, client_queue: asyncio.Queue) -> None:
        """
        Remove a disconnected client's queue.

        Called when client disconnects or stream ends. This prevents
        memory leaks and ensures we don't try to send to dead connections.
        """
        if client_queue in self._clients:
            self._clients.remove(client_queue)

    async def broadcast(self, message: str, event: Optional[str] = None) -> None:
        """
        Send a message to ALL connected clients simultaneously.

        This creates one ServerSentEvent and puts it into every client's queue.
        Each client's BroadcastStream will then yield this event independently.

        Design choice: We use put_nowait() to avoid blocking if a client's
        queue is full. In production, you might want to handle QueueFull
        exceptions by either dropping the message or disconnecting slow clients.
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
            self.remove_client(client_queue)

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
