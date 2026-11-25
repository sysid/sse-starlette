# /// script
# requires-python = ">=3.10"
# dependencies = ["sse-starlette", "uvicorn"]
# ///
"""Limit active SSE responses within one worker/event loop.

Run: python examples/08_connection_limits.py
Open two terminals with: curl -N http://localhost:8000/events
The second stream waits until the first finishes or disconnects.
Queued requests and total TCP connections are not bounded by this example.
"""

import asyncio

from starlette.applications import Starlette
from starlette.routing import Route

from sse_starlette import EventSourceResponse


class LimitedEventSourceResponse(EventSourceResponse):
    def __init__(self, content, semaphore, **kwargs):
        super().__init__(content, **kwargs)
        self.semaphore = semaphore

    async def __call__(self, scope, receive, send):
        async with self.semaphore:
            await super().__call__(scope, receive, send)


async def generate_events():
    for number in range(10):
        yield {"data": number}
        await asyncio.sleep(1)


class ConnectionLimiter:
    def __init__(self, max_connections=100):
        self.semaphore = asyncio.Semaphore(max_connections)

    async def limited_endpoint(self, request):
        return LimitedEventSourceResponse(generate_events(), self.semaphore)


# Reuse one limiter for all routes sharing the limit.
limiter = ConnectionLimiter(max_connections=1)
app = Starlette(routes=[Route("/events", limiter.limited_endpoint)])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
