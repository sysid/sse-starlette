import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from sse_starlette.sse import EventSourceResponse

_log = logging.getLogger(__name__)


async def numbers(minimum, maximum):
    """ Simulates and limited stream """
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(0.9)
        yield dict(data=i)


async def endless(req: Request):
    """ Simulates and endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise there will be dangling tasks preventing proper shutdown.
    """

    async def event_publisher():
        i = 0

        while True:
            disconnected = await req.is_disconnected()
            if disconnected:
                _log.info(f"Disconnecting client {req.client}")
                break
            # yield dict(id=..., event=..., data=...)
            i += 1
            yield dict(data=i)
            await asyncio.sleep(0.9)
        _log.info(f"Disconnected from client {req.client}")

    return EventSourceResponse(event_publisher())


async def sse(request):
    generator = numbers(1, 5)
    return EventSourceResponse(generator)


routes = [
    Route("/", endpoint=sse),
    Route("/endless", endpoint=endless),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level='info')
