import asyncio
import logging

import anyio
import pytest
from httpx import AsyncClient
from sse_starlette import EventSourceResponse
from starlette.testclient import TestClient

_log = logging.getLogger(__name__)

"""
Integration test for lost client connection:

1. start example.py with log_level='trace'
2. curl http://localhost:8000/endless
3. kill curl

expected outcome:
all streaming stops, including pings (log output)


Integration test for uvicorn shutdown (Ctrl-C) with long running task
1. start example.py with log_level='trace'
2. curl http://localhost:8000/endless
3. CTRL-C: stop server

expected outcome:
server shut down gracefully, no pending tasks
"""


@pytest.mark.parametrize(
    "input,expected",
    [
        ("integer", b"data: 1\r\n\r\n"),
        ("dict1", b"data: 1\r\n\r\n"),
        ("dict2", b"event: message\r\ndata: 1\r\n\r\n"),
    ],
)
def test_sync_event_source_response(input, expected):
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
        response = EventSourceResponse(generator, ping=0.2)  # type: ignore
        await response(scope, receive, send)

    client = TestClient(app)
    response = client.get("/")
    assert response.content.decode().count("ping") == 2
    assert expected in response.content
    print(response.content)


@pytest.mark.anyio
async def test_endless():
    async def app(scope, receive, send):
        async def event_publisher():
            i = 0
            try:
                while True:
                    i += 1
                    _log.info(f"yielding {i=}")
                    yield dict(data=i)
                    await asyncio.sleep(0.9)
            except asyncio.CancelledError as e:
                raise e

        response = EventSourceResponse(event_publisher())
        await response(scope, receive, send)

    with pytest.raises(TimeoutError):
        async with AsyncClient(app=app, base_url="http://localhost:8000") as client:
            with anyio.fail_after(1) as scope:
                async with anyio.create_task_group() as tg:
                    async with client.stream("GET", "/") as response:
                        # https://www.python-httpx.org/async/#streaming-responses
                        pass


@pytest.mark.anyio
async def test_endless_full(client, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(TimeoutError):
        with anyio.fail_after(1) as scope:
            try:
                async with anyio.create_task_group() as tg:
                    # https://www.python-httpx.org/async/#streaming-responses
                    tg.start_soon(client.get, "/endless")
            finally:
                # The cancel_called property will be True if timeout was reached
                assert scope.cancel_called is True
                assert "chunk: data: 3" in caplog.text


def test_header_charset():
    async def numbers(minimum, maximum):
        for i in range(minimum, maximum + 1):
            await asyncio.sleep(0.1)
            yield i

    generator = numbers(1, 5)
    response = EventSourceResponse(generator, ping=0.2)  # type: ignore
    content_type = [h for h in response.raw_headers if h[0].decode() == "content-type"]
    assert content_type == [(b"content-type", b"text/event-stream; charset=utf-8")]
