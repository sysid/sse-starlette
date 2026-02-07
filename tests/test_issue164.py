"""
Regression tests for Issue #164: SSE connection doesn't disconnect properly
with BaseHTTPMiddleware during server shutdown.

Root cause: _stream_response only sends the closing frame (more_body=False)
on normal completion (generator exhausted). When cancelled (shutdown signal),
the closing frame is never sent. Without middleware, uvicorn closes the TCP
socket directly. With middleware, the response must be properly terminated
through the ASGI protocol via the closing frame.

Fix: Send the closing frame in a finally block so it's always sent.
"""

import asyncio
import logging
import math

import anyio
import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from sse_starlette.sse import AppStatus, EventSourceResponse

_log = logging.getLogger(__name__)


class TestIssue164MiddlewareShutdown:
    """Regression tests for Issue #164: closing frame on cancellation."""

    @pytest.mark.anyio
    async def test_closing_frame_sent_on_cancellation(self):
        """When EventSourceResponse is cancelled externally (e.g., by shutdown
        or middleware timeout), it should send the closing frame (more_body=False)
        so the HTTP response is properly terminated."""
        sent_messages = []

        async def event_publisher():
            try:
                while True:
                    yield {"data": "event"}
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

        async def mock_send(message):
            sent_messages.append(message)

        async def mock_receive():
            await anyio.sleep(float("inf"))
            return {"type": "http.disconnect"}

        response = EventSourceResponse(event_publisher(), ping=100)

        # Cancel from outside after some events have been sent
        with anyio.move_on_after(0.35):
            await response({}, mock_receive, mock_send)

        # Verify closing frame was sent
        closing_frames = [
            m
            for m in sent_messages
            if m.get("type") == "http.response.body" and m.get("more_body") is False
        ]
        assert len(closing_frames) == 1, (
            "Expected closing frame (more_body=False) to be sent on cancellation"
        )

    @pytest.mark.anyio
    async def test_middleware_channel_receives_closing_frame(self):
        """Simulate BaseHTTPMiddleware's channel pattern: EventSourceResponse
        writes to a memory channel, and a consumer reads from it.

        The closing frame must go through the channel so the middleware's
        outer _StreamingResponse can properly terminate the HTTP response."""
        received_messages = []

        async def event_publisher():
            try:
                while True:
                    yield {"data": "event"}
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

        # Simulate BaseHTTPMiddleware's channel-based send
        send_stream, recv_stream = anyio.create_memory_object_stream(
            max_buffer_size=math.inf
        )

        async def channel_send(message):
            """Like BaseHTTPMiddleware's send_no_error."""
            try:
                await send_stream.send(message)
            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                pass

        async def mock_receive():
            await anyio.sleep(float("inf"))
            return {"type": "http.disconnect"}

        response = EventSourceResponse(event_publisher(), ping=100)

        async with anyio.create_task_group() as tg:
            # Consumer: reads from channel (like middleware's body_stream)
            async def consume():
                async for message in recv_stream:
                    received_messages.append(message)

            tg.start_soon(consume)

            # Producer: runs EventSourceResponse, cancel after 0.35s
            with send_stream:
                with anyio.move_on_after(0.35):
                    await response({}, mock_receive, channel_send)

            # send_stream closed here (exiting `with send_stream:`)
            # Consumer will get EndOfStream and finish

        # Verify closing frame went through the channel
        closing_frames = [
            m
            for m in received_messages
            if m.get("type") == "http.response.body" and m.get("more_body") is False
        ]
        assert len(closing_frames) == 1, (
            "Expected closing frame (more_body=False) to go through the channel"
        )

    @pytest.mark.anyio
    async def test_with_actual_base_http_middleware(self):
        """Integration test with real BaseHTTPMiddleware.

        Reproduces the exact scenario from Issue #164: EventSourceResponse
        wrapped in BaseHTTPMiddleware, shutdown triggered via AppStatus.
        Verifies the response terminates (not hangs) and sends closing frame.
        """
        sent_messages = []

        async def inner_app(scope, receive, send):
            async def event_publisher():
                try:
                    while True:
                        yield {"data": "event"}
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    raise

            response = EventSourceResponse(event_publisher(), ping=100)
            await response(scope, receive, send)

        class LoggingMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                response = await call_next(request)
                return response

        app = LoggingMiddleware(inner_app)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "headers": [],
            "path": "/sse",
            "root_path": "",
            "query_string": b"",
            "server": ("testserver", 80),
        }

        async def mock_receive():
            await anyio.sleep(float("inf"))
            return {"type": "http.disconnect"}

        async def mock_send(message):
            sent_messages.append(message)

        # Run middleware + SSE; trigger shutdown after events flow.
        # fail_after(3) prevents hanging if the fix doesn't work.
        with anyio.fail_after(3):
            async with anyio.create_task_group() as tg:

                async def trigger_shutdown():
                    await asyncio.sleep(0.35)
                    AppStatus.should_exit = True

                tg.start_soon(trigger_shutdown)
                await app(scope, mock_receive, mock_send)

        # Verify closing frame sent through the full middleware stack
        closing_frames = [
            m
            for m in sent_messages
            if m.get("type") == "http.response.body" and m.get("more_body") is False
        ]
        assert len(closing_frames) == 1, (
            "Expected closing frame (more_body=False) through middleware"
        )

        # Verify events were actually streamed before shutdown
        event_bodies = [
            m
            for m in sent_messages
            if m.get("type") == "http.response.body"
            and m.get("more_body") is True
            and m.get("body", b"") != b""
        ]
        assert len(event_bodies) >= 2, "Expected events to have been streamed"
