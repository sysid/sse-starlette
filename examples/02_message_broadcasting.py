"""
Message broadcasting example using asyncio.Queue for real-time communication.

This example demonstrates:
- Queue-based message broadcasting
- Multiple clients receiving the same messages
- REST API for sending messages
- Proper queue management and cleanup

Usage:
    python 02_message_broadcasting.py

Test with curl:
    # Subscribe to messages (keep this running in one terminal)
    curl -N http://localhost:8000/events

    # Get connected clients count
    curl -N http://localhost:8000/status

    # Send messages from another terminal
    curl -X POST "http://localhost:8000/send" -H "Content-Type: application/json" -d '{"message": "Hello World"}'
    curl -X POST "http://localhost:8000/send" -H "Content-Type: application/json" -d '{"message": "This is a test"}'

    # Send message with event type
    curl -X POST "http://localhost:8000/send" -H "Content-Type: application/json" -d '{"message": "Alert!", "event": "alert"}'
"""

import asyncio
import logging
from typing import AsyncGenerator, Dict, List, Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from sse_starlette import EventSourceResponse, ServerSentEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    """Request model for sending messages."""
    message: str
    event: Optional[str] = None
    id: Optional[str] = None


class MessageBroadcaster:
    """Manages message broadcasting to multiple SSE clients."""

    def __init__(self):
        self._clients: List[asyncio.Queue] = []
        self._message_count = 0

    def add_client(self) -> asyncio.Queue:
        """Add a new client queue and return it."""
        client_queue = asyncio.Queue()
        self._clients.append(client_queue)
        logger.info(f"Client connected. Total clients: {len(self._clients)}")
        return client_queue

    def remove_client(self, client_queue: asyncio.Queue) -> None:
        """Remove a client queue."""
        if client_queue in self._clients:
            self._clients.remove(client_queue)
            logger.info(f"Client disconnected. Total clients: {len(self._clients)}")

    async def broadcast_message(self, message: str, event: Optional[str] = None,
                                message_id: Optional[str] = None) -> None:
        """Broadcast a message to all connected clients."""
        if not self._clients:
            logger.warning("No clients connected to receive message")
            return

        self._message_count += 1
        if not message_id:
            message_id = str(self._message_count)

        sse_event = ServerSentEvent(
            data=message,
            event=event,
            id=message_id
        )

        # Send to all clients
        disconnected_clients = []
        for client_queue in self._clients:
            try:
                client_queue.put_nowait(sse_event)
            except asyncio.QueueFull:
                logger.warning("Client queue full, marking for removal")
                disconnected_clients.append(client_queue)

        # Clean up disconnected clients
        for client_queue in disconnected_clients:
            self.remove_client(client_queue)

        logger.info(f"Broadcasted message to {len(self._clients)} clients")

    @property
    def client_count(self) -> int:
        """Get the current number of connected clients."""
        return len(self._clients)


# Global broadcaster instance
broadcaster = MessageBroadcaster()
app = FastAPI(title="SSE Message Broadcasting")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def event_stream(request: Request) -> AsyncGenerator[ServerSentEvent, None]:
    """Generate SSE events from the client's message queue."""
    client_queue = broadcaster.add_client()

    try:
        while True:
            # Check if client is still connected
            if await request.is_disconnected():
                break

            try:
                # Wait for next message with timeout to allow disconnect checks
                message = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                # Send periodic ping to keep connection alive
                yield ServerSentEvent(comment="ping")
                continue

    except asyncio.CancelledError:
        logger.info("Client stream cancelled")
        raise
    finally:
        broadcaster.remove_client(client_queue)


@app.get("/events")
async def sse_endpoint(request: Request) -> EventSourceResponse:
    """SSE endpoint for receiving broadcasted messages."""
    return EventSourceResponse(event_stream(request))


@app.post("/send")
async def send_message(message_request: MessageRequest) -> Dict[str, str]:
    """Send a message to all connected SSE clients."""
    await broadcaster.broadcast_message(
        message=message_request.message,
        event=message_request.event,
        message_id=message_request.id
    )

    return {
        "status": "sent",
        "message": message_request.message,
        "clients": str(broadcaster.client_count)
    }


@app.get("/status")
async def get_status() -> Dict[str, int]:
    """Get the current status of connected clients."""
    return {"connected_clients": broadcaster.client_count}


@app.on_event("startup")
async def startup_event():
    """Send a welcome message on startup."""
    await asyncio.sleep(0.1)  # Small delay to ensure setup is complete
    await broadcaster.broadcast_message("Server started", event="system")


if __name__ == "__main__":
    print("Starting SSE message broadcasting server...")
    print("Available endpoints:")
    print("  - GET  http://localhost:8000/events (subscribe to messages)")
    print("  - POST http://localhost:8000/send (send message to all clients)")
    print("  - GET  http://localhost:8000/status (get client count)")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
