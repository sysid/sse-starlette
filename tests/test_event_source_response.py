import asyncio
import logging
import math
from functools import partial

import anyio
import anyio.lowlevel
import pytest
from starlette.testclient import TestClient

from sse_starlette import EventSourceResponse
from sse_starlette.sse import SendTimeoutError
from tests.anyio_compat import collapse_excgroups

_log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "input,sep,expected",
    [
        ("integer", "\r\n", b"data: 1\r\n\r\n"),
        ("dict1", "\r\n", b"data: 1\r\n\r\n"),
        ("dict2", "\r\n", b"event: message\r\ndata: 1\r\n\r\n"),
        ("dict2", "\r", b"event: message\rdata: 1\r\r"),
    ],
)
async def test_sync_event_source_response(reset_appstatus_event, input, sep, expected):
    async def app(scope, receive, send):
        async def numbers(minimum, maximum):
            for i in range(minimum, maximum + 1):
                await asyncio.sleep(0.1)
                if input == "integer":
                    yield i
                elif input == "dict1":
                    yield dict(data=i)
                elif input == "dict2":
                    yield dict(data=i, event="message")

        generator = numbers(1, 5)
        response = EventSourceResponse(generator, ping=0.2, sep=sep)  # type: ignore
        await response(scope, receive, send)

    client = TestClient(app)
    response = client.get("/")
    assert response.content.decode().count("ping") == 2
    assert expected in response.content
    print(response.content)


@pytest.mark.parametrize(
    "input,expected",
    [
        ("integer", b"data: 1\r\n\r\n"),
        ("dict1", b"data: 1\r\n\r\n"),
        ("dict2", b"event: message\r\ndata: 1\r\n\r\n"),
    ],
)
def test_sync_memory_channel_event_source_response(
    reset_appstatus_event, input, expected
):
    async def app(scope, receive, send):
        send_chan, recv_chan = anyio.create_memory_object_stream(math.inf)

        async def numbers(inner_send_chan, minimum, maximum):
            async with send_chan:
                for i in range(minimum, maximum + 1):
                    await anyio.sleep(0.1)

                    if input == "integer":
                        await inner_send_chan.send(i)
                    elif input == "dict1":
                        await inner_send_chan.send(dict(data=i))
                    elif input == "dict2":
                        await inner_send_chan.send(dict(data=i, event="message"))

        response = EventSourceResponse(
            recv_chan, data_sender_callable=partial(numbers, send_chan, 1, 5), ping=0.2
        )  # type: ignore
        await response(scope, receive, send)

    client = TestClient(app)
    response = client.get("/")
    assert response.content.decode().count("ping") == 2
    assert expected in response.content
    print(response.content)


@pytest.mark.anyio
async def test_disconnect_from_client(httpx_client, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(TimeoutError):
        with anyio.fail_after(1) as scope:
            try:
                async with anyio.create_task_group() as tg:
                    # https://www.python-httpx.org/async/#streaming-responses
                    tg.start_soon(httpx_client.get, "/endless")
            finally:
                # The cancel_called property will be True if timeout was reached
                assert scope.cancel_called is True
                assert "chunk: b'data: 4\\r\\n\\r\\n'" in caplog.text
                assert "Disconnected from client" in caplog.text


@pytest.mark.anyio
async def test_ping_concurrency(reset_appstatus_event):
    # Sequencing here is as follows:
    # t=0.5s - event_publisher sends the first response item,
    #          claiming the lock and going to sleep for 1 second so until t=1.5s.
    # t=1.0s - ping task wakes up and tries to call send while we know
    #          that event_publisher is still blocked inside it and holding the lock
    lock = anyio.Lock()

    async def event_publisher():
        for i in range(0, 2):
            await anyio.sleep(0.5)
            yield i

    async def send(*args, **kwargs):
        # Raises WouldBlock if called while someone else already holds the lock
        lock.acquire_nowait()
        await anyio.sleep(1.0)
        # noinspection PyAsyncCall
        lock.release()

    async def receive():
        await anyio.lowlevel.checkpoint()
        return {"type": "something"}

    response = EventSourceResponse(event_publisher(), ping=1)
    with pytest.raises(anyio.WouldBlock):
        with collapse_excgroups():
            await response({}, receive, send)


def test_header_charset(reset_appstatus_event):
    async def numbers(minimum, maximum):
        for i in range(minimum, maximum + 1):
            await anyio.sleep(0.1)
            yield i

    generator = numbers(1, 5)
    response = EventSourceResponse(generator, ping=0.2)  # type: ignore
    content_type = [h for h in response.raw_headers if h[0].decode() == "content-type"]
    assert content_type == [(b"content-type", b"text/event-stream; charset=utf-8")]


@pytest.mark.anyio
async def test_send_timeout(reset_appstatus_event):
    # Timeout is set to 0.5s, but `send` will take 1s. Expect SendTimeoutError.
    cleanup = False

    async def event_publisher():
        try:
            yield {"event": "some", "data": "any"}
            assert False  # never reached
        finally:
            nonlocal cleanup
            cleanup = True

    async def send(*args, **kwargs):
        await anyio.sleep(1.0)

    async def receive():
        await anyio.lowlevel.checkpoint()
        return {"type": "something"}

    response = EventSourceResponse(event_publisher(), send_timeout=0.5)
    with pytest.raises(SendTimeoutError):
        with collapse_excgroups():
            await response({}, receive, send)

    assert cleanup
