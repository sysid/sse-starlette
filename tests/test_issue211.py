"""
Regression test for Issue #211: AppStatus.should_exit latches process-wide.

Problem: Since 3.1.1, _shutdown_watcher copies the captured uvicorn server's
should_exit into the process-global AppStatus.should_exit and never clears it.
Once any uvicorn server in the process has stopped, every later
EventSourceResponse returns from _listen_for_exit_signal immediately and is
cancelled before its first event. The client sees a truncated chunked body.

Typical trigger: a test suite that starts a real uvicorn server per test.

Second failure mode: the watcher resolved the uvicorn server once at start. A
watcher still sleeping when server1 stops outlives it; server2's streams then
register on that watcher, which sees server1.should_exit on its next poll and
cancels them. Hence the zero gap between servers.

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

# Longer than the watcher's 0.5s poll interval: a poll always happens while a
# stream is open, which makes the stale-watcher case deterministic.
FIRST_EVENT_DELAY = 0.6


async def _events(_request):
    async def generator():
        # First event arrives later, as in a real stream.
        await anyio.sleep(FIRST_EVENT_DELAY)
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
    @pytest.mark.parametrize(
        "gap_between_servers",
        [
            # Watcher that saw server1 is still alive when server2's request arrives.
            pytest.param(0.0, id="within-watcher-poll-interval"),
            # Watcher polls every 0.5s; two intervals guarantee it observed server1's exit.
            pytest.param(1.1, id="after-watcher-observed-exit"),
        ],
    )
    async def test_eventSourceResponse_whenEarlierUvicornServerStopped_thenLaterServerStreamsEvents(
        self, gap_between_servers
    ):
        app = Starlette(routes=[Route("/events", _events)])

        with anyio.fail_after(10):
            first_body = await _serve_once_and_fetch_events(app)
            assert "data: hello" in first_body

            await anyio.sleep(gap_between_servers)

            # Before the fix: RemoteProtocolError (incomplete chunked read),
            # because the stopped first server latched AppStatus.should_exit
            # or a still-running watcher held a reference to it.
            second_body = await _serve_once_and_fetch_events(app)
            assert "data: hello" in second_body
