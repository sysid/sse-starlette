"""Regression test for Issue #218: EventSourceResponse streams forever on HEAD.

Problem: Starlette adds ``HEAD`` to every GET route, so an SSE endpoint also
answers HEAD. ``EventSourceResponse`` has no HEAD handling: it sends the
headers and starts the stream, the ASGI server discards the body bytes but
still waits for ``more_body=False``, and the stream only sends that once the
generator ends. The response therefore never completes.

Two consequences:

1. The connection is stuck for good. A keep-alive client or reverse proxy
   that reuses it hangs on its next request. nginx does this: it returns a
   HEAD's upstream connection to its pool as soon as the headers arrive.
2. The handler and the socket leak. If a follow-up request is waiting on
   that connection, the server pauses reading and never sees the client
   close, so the handler, its session and the socket stay alive.

The fix answers HEAD with the headers and an empty body, without opening the
stream, matching Starlette's ``FileResponse``.
"""

from __future__ import annotations

import anyio
import httpx2 as httpx
import pytest
from httpx2 import ASGITransport
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.routing import Route

from sse_starlette import EventSourceResponse

# A regression would hang here, so fail fast instead of blocking the suite.
TIMEOUT = 5


def _http_scope(method: str) -> dict:
    """Build a minimal ASGI HTTP scope."""
    return {
        "type": "http",
        "method": method,
        "headers": [],
        "path": "/events",
        "raw_path": b"/events",
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 5000),
        "root_path": "",
        "http_version": "1.1",
    }


@pytest.mark.asyncio
async def test_head_whenCalled_thenResponseCompletesWithoutStreaming():
    """A HEAD request must complete instead of streaming forever."""
    started = False

    async def generator():
        nonlocal started
        started = True
        while True:
            yield {"data": "never"}
            await anyio.sleep(0.01)

    response = EventSourceResponse(generator(), ping=0.05)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - never awaited, the stream must not start
        await anyio.sleep_forever()

    with anyio.fail_after(TIMEOUT):
        await response(_http_scope("HEAD"), receive, send)

    types = [m["type"] for m in sent]
    assert types == ["http.response.start", "http.response.body"], types

    body = sent[-1]
    assert body["body"] == b""
    assert body["more_body"] is False, "the response must be complete"

    assert started is False, "HEAD must not start the event stream"


@pytest.mark.asyncio
async def test_head_whenCalled_thenHeadersMatchTheStreamedResponse():
    """HEAD must return the headers a GET would return."""

    async def generator():
        yield {"data": "hello"}

    response = EventSourceResponse(generator(), ping=0.05)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover
        await anyio.sleep_forever()

    with anyio.fail_after(TIMEOUT):
        await response(_http_scope("HEAD"), receive, send)

    start = sent[0]
    assert start["status"] == 200

    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_head_whenBackgroundTaskIsSet_thenBackgroundTaskRuns():
    """The background task must still run, as it does for Starlette's responses.

    The generator never ends, so on the unfixed code the response never
    completes and the background task never runs.
    """
    ran = False

    async def on_complete():
        nonlocal ran
        ran = True

    async def generator():
        while True:
            yield {"data": "never"}
            await anyio.sleep(0.01)

    response = EventSourceResponse(
        generator(), ping=0.05, background=BackgroundTask(on_complete)
    )

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover
        await anyio.sleep_forever()

    with anyio.fail_after(TIMEOUT):
        await response(_http_scope("HEAD"), receive, send)

    assert ran is True, "the background task must run for HEAD as well"


@pytest.mark.asyncio
async def test_get_whenCalled_thenStreamIsUnaffected():
    """The HEAD short-circuit must not change GET behaviour."""

    async def generator():
        yield {"data": "one"}
        yield {"data": "two"}

    response = EventSourceResponse(generator(), ping=0.05)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        await anyio.sleep_forever()

    with anyio.fail_after(TIMEOUT):
        await response(_http_scope("GET"), receive, send)

    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    assert b"data: one" in body
    assert b"data: two" in body


@pytest.mark.asyncio
async def test_head_overHttp_whenRequested_thenTheResponseCompletes():
    """End to end through Starlette: a HEAD must not hang the request."""

    async def events(request):
        async def generator():
            i = 0
            while True:
                i += 1
                yield {"data": str(i)}
                await anyio.sleep(0.01)

        return EventSourceResponse(generator(), ping=0.05)

    app = Starlette(routes=[Route("/events", events)])

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as client:
        with anyio.fail_after(TIMEOUT):
            response = await client.head("/events")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.content == b""
