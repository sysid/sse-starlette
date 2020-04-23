import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from sse_starlette.sse import EventSourceResponse

_log = logging.getLogger(__name__)


async def numbers(minimum, maximum):
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(0.9)
        yield dict(data=i)


async def endless_numbers():
    i = 0
    while True:
        await asyncio.sleep(0.3)
        i += 1
        yield dict(data=i)


async def sse(request):
    # generator = numbers(1, 5)
    generator = endless_numbers()
    return EventSourceResponse(generator)


routes = [
    Route("/", endpoint=sse)
]

app = Starlette(debug=True, routes=routes)


@app.route('/streaming-endpoint', methods=['GET'])
async def stream_stats(req: Request):
    async def event_publisher():
        i = 0
        while True:
            # yield dict(id=..., event=..., data=...)
            i += 1
            yield dict(data=i)
            await asyncio.sleep(0.2)

    return EventSourceResponse(event_publisher())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level='info')
