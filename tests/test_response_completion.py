"""
The closing ``more_body=False`` message must be sent unless the client is gone.

Two ways it went missing:

1. Final-send race: ``_stream_response`` set ``active = False`` before awaiting the
   closing send. A receive() that returned anything other than ``http.disconnect``
   while that send was suspended let ``_listen_for_disconnect`` exit its loop, and
   ``cancel_on_finish`` cancelled the closing send.
2. Exit signal: on server shutdown the task group is cancelled while
   ``_stream_response`` is still running, so nothing sends the closing body. The ASGI
   server sees a started, unfinished response (uvicorn: "ASGI callable returned
   without completing response"; client: truncated chunked body).
"""

import asyncio
import socket

import anyio
import httpx2 as httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from sse_starlette.sse import AppStatus, EventSourceResponse

FINAL = {"type": "http.response.body", "body": b"", "more_body": False}
SCOPE = {"type": "http", "method": "GET", "headers": []}
WATCHER_DETECT_TIMEOUT = 0.5 + 0.2  # watcher polls every 0.5s


async def _blocking_receive():
    await anyio.sleep_forever()


def _closing_messages(sent):
    return [m for m in sent if m == FINAL]


@pytest.mark.anyio
async def test_finalSend_whenReceiveReturnsDuringIt_thenClosingBodyIsStillSent():
    final_started = anyio.Event()
    listener_woke = anyio.Event()
    sent = []
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            await final_started.wait()
            listener_woke.set()
            # Not a disconnect: the listener must keep waiting, not end the response.
            return {"type": "http.request", "body": b"", "more_body": False}
        await anyio.sleep_forever()

    async def send(message):
        if message == FINAL:
            final_started.set()
            await listener_woke.wait()
            await anyio.sleep(0)
        sent.append(message)

    async def events():
        yield {"data": "last"}

    with anyio.fail_after(2):
        await EventSourceResponse(events(), ping=0)(SCOPE, receive, send)

    assert _closing_messages(sent) == [FINAL]


@pytest.mark.anyio
async def test_normalCompletion_whenStreamEnds_thenClosingBodySentOnce():
    sent = []

    async def send(message):
        sent.append(message)

    async def events():
        yield {"data": "a"}
        yield {"data": "b"}

    with anyio.fail_after(2):
        await EventSourceResponse(events(), ping=0)(SCOPE, _blocking_receive, send)

    assert sent[-1] == FINAL
    assert _closing_messages(sent) == [FINAL]


@pytest.mark.anyio
async def test_exitSignal_whenStreamIsOpen_thenClosingBodyIsSent():
    sent = []
    cancelled = False

    async def send(message):
        sent.append(message)

    async def events():
        nonlocal cancelled
        try:
            yield {"data": "first"}
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            cancelled = True
            raise

    async def trigger_exit():
        await anyio.sleep(0.1)
        AppStatus.should_exit = True

    with anyio.fail_after(WATCHER_DETECT_TIMEOUT + 1):
        async with anyio.create_task_group() as tg:
            tg.start_soon(trigger_exit)
            await EventSourceResponse(events(), ping=0)(SCOPE, _blocking_receive, send)

    assert cancelled, "the generator is still force-cancelled on shutdown"
    assert sent[0]["type"] == "http.response.start"
    assert sent[-1] == FINAL
    assert _closing_messages(sent) == [FINAL]


@pytest.mark.anyio
async def test_exitSignal_whenAlreadySetAtStart_thenResponseIsEmptyButComplete():
    AppStatus.should_exit = True
    sent = []

    async def send(message):
        sent.append(message)

    async def events():
        await anyio.sleep_forever()
        yield {"data": "never"}  # pragma: no cover

    with anyio.fail_after(2):
        await EventSourceResponse(events(), ping=0)(SCOPE, _blocking_receive, send)

    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[-1] == FINAL


@pytest.mark.anyio
async def test_clientDisconnect_whenStreamIsOpen_thenNoClosingBodyIsSent():
    sent = []

    async def receive():
        await anyio.sleep(0.1)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def events():
        yield {"data": "first"}
        await anyio.sleep_forever()

    with anyio.fail_after(2):
        await EventSourceResponse(events(), ping=0)(SCOPE, receive, send)

    assert _closing_messages(sent) == []


@pytest.mark.anyio
async def test_exitSignal_whenServingWithUvicorn_thenClientGetsCompleteBody():
    async def endpoint(_request):
        async def events():
            yield {"data": "hello"}
            await anyio.sleep_forever()

        return EventSourceResponse(events(), ping=0)

    app = Starlette(routes=[Route("/events", endpoint)])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)

        async def stop_server():
            await anyio.sleep(0.2)
            server.should_exit = True  # what uvicorn's SIGTERM handler sets

        async with httpx.AsyncClient() as client, anyio.create_task_group() as tg:
            tg.start_soon(stop_server)
            with anyio.fail_after(WATCHER_DETECT_TIMEOUT + 2):
                response = await client.get(f"http://127.0.0.1:{port}/events")
    finally:
        server.should_exit = True
        await serve_task

    assert response.status_code == 200
    assert "data: hello" in response.text
