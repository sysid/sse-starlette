import asyncio
import logging
from functools import partial
from typing import Callable, Coroutine

import anyio
import httpx
import pytest
from httpx import AsyncClient

from sse_starlette import EventSourceResponse

_log = logging.getLogger(__name__)


@pytest.mark.anyio
async def test_x():
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

    async with AsyncClient(app=app, base_url="http://localhost:8000") as ac:
        results = await asyncio.gather(
            ac.get("/"),
            # ac.post("/api/v2/plan", headers=user_header, json=json_payload),
            # ac.post("/api/v2/plan", headers=user_header, json=json_payload),
        )
        response = results[0]
        assert response.content.decode().count("ping") == 2


@pytest.mark.anyio
async def test_xxx():
    _log.info("xxxxxxxxxxx")

    async def app(scope, receive, send):
        async def event_publisher():
            i = 0
            try:
                while True:
                    # yield dict(id=..., event=..., data=...)
                    i += 1
                    _log.info(f"yielding {i=}")
                    yield dict(data=i)
                    await asyncio.sleep(0.9)
            except asyncio.CancelledError as e:
                # _log.info(f"Disconnected from client (via refresh/close) {req.client}")
                # Do any other cleanup, if any
                raise e

        response = EventSourceResponse(event_publisher())
        await response(scope, receive, send)

    print("yyyy")
    _log.info("xxxxxxxxxxx")

    ac = AsyncClient(app=app, base_url="http://localhost:8000")
    async with ac.stream("GET", "http://localhost:8000/") as response:
        async for chunk in response.aiter_bytes():
            print(chunk)
    # async with AsyncClient(app=app, base_url="http://localhost:8000") as ac:
    #     results = await asyncio.gather(
    #         ac.get("/"),
    #         # ac.post("/api/v2/plan", headers=user_header, json=json_payload),
    #         # ac.post("/api/v2/plan", headers=user_header, json=json_payload),
    #     )
    #     _ = None
    #     # await asyncio.sleep(10000)
    #     # for result in results:
    #     #     assert result.status_code == 201


@pytest.mark.asyncio
async def test_home(client):
    print("Testing")
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, world!"
    print("OK")


# https://www.python-httpx.org/async/#streaming-responses
@pytest.mark.asyncio
async def test_endless(client):
    print("Testing endless")
    async with client.stream('GET', "/endless") as response:
        async for chunk in response.aiter_bytes():
            print(chunk)

# https://www.python-httpx.org/async/#streaming-responses
@pytest.mark.anyio
async def test_endless2(client):
    loop = asyncio.get_event_loop()
    print("Testing endless")

    async with anyio.create_task_group() as tg:
        async def wrap(func: Callable[[], Coroutine[None, None, None]]) -> None:
            await func()
            # noinspection PyAsyncCall
            tg.cancel_scope.cancel()

        with anyio.fail_after(1) as scope:
            tg.start_soon(wrap, partial(client.get, "/endless"))
            await asyncio.sleep(1)

        # The cancel_called property will be True if timeout was reached
        print('Exited cancel scope, cancelled =', scope.cancel_called)

    # async with client.stream('GET', '/endless') as response:
    #     async for chunk in response.aiter_bytes():
    #         print(chunk)

    # req = client.build_request("GET", "/endless")
    # response = await client.send(req, stream=True)
    # # async for chunk in response.aiter_lines():
    # #     print(f"Data: {chunk=}")
    # await asyncio.sleep(1)
    # await client.aclose()


    # return StreamingResponse(r.aiter_text(), background=BackgroundTask(r.aclose))
    _ = None
