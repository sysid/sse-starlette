# main.py
import asyncio
import logging

from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

_log = logging.getLogger(__name__)


async def endless(req: Request):
    async def event_publisher():
        i = 0
        try:
            while True:  # i <= 20:
                # yield dict(id=..., event=..., data=...)
                i += 1
                # print(f"Sending {i}")
                yield dict(data=i)
                await asyncio.sleep(0.3)
        except asyncio.CancelledError as e:
            _log.info(f"Disconnected from client (via refresh/close) {req.client}")
            # Do any other cleanup, if any
            raise e

    return EventSourceResponse(event_publisher())


app = Starlette(
    routes=[Route("/endless", endpoint=endless)],
)
