"""
Regression test for Issue #211: AppStatus.should_exit latches process-wide.

Problem: Since 3.1.1, _shutdown_watcher copies the captured uvicorn server's
should_exit into the process-global AppStatus.should_exit and never clears it.
Once any uvicorn server in the process has stopped, every later
EventSourceResponse returns from _listen_for_exit_signal immediately and is
cancelled before its first event. The client sees a truncated chunked body.

Typical trigger: a test suite that starts a real uvicorn server per test.

Both servers run inside ONE test on purpose: the autouse reset_shutdown_state
fixture resets AppStatus.should_exit between tests and would mask the bug.
"""

import asyncio
import socket

import anyio
import httpx2 as httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from sse_starlette.sse import EventSourceResponse

# Watcher polls every 0.5s; two intervals guarantee it has observed server1's exit.
WATCHER_OBSERVES_EXIT_DELAY = 1.1


async def _events(_request):
    async def generator():
        # First event arrives a moment later, as in a real stream.
        await anyio.sleep(0.1)
        yield {"data": "hello"}

    return EventSourceResponse(generator())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve_once_and_fetch_events(app: Starlette) -> str:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{port}/events")
            return response.text
    finally:
        # Programmatic stop, as test harnesses and embedded servers do.
        server.should_exit = True
        await serve_task


class TestIssue211ShouldExitLatch:
    @pytest.mark.asyncio
    async def test_eventSourceResponse_whenEarlierUvicornServerStopped_thenLaterServerStreamsEvents(
        self,
    ):
        app = Starlette(routes=[Route("/events", _events)])

        with anyio.fail_after(10):
            first_body = await _serve_once_and_fetch_events(app)
            assert "data: hello" in first_body

            await anyio.sleep(WATCHER_OBSERVES_EXIT_DELAY)

            # Before the fix: RemoteProtocolError (incomplete chunked read),
            # because the stopped first server latched AppStatus.should_exit.
            second_body = await _serve_once_and_fetch_events(app)
            assert "data: hello" in second_body
