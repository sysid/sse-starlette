import asyncio

# example by: justindujardin
#
# tests proper shutdown in case no messages are yielded:
# no yielded messages would get into the old codepath that checks AppStatus

import uvicorn
from fastapi import FastAPI
from starlette.requests import Request
from uvicorn.config import logger as _log

from sse_starlette.sse import EventSourceResponse

app = FastAPI()

items = {}


@app.get("/endless")
async def endless(req: Request):
    """Simulates and endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise there will be dangling tasks preventing proper shutdown.
    """

    async def event_publisher():
        # The event publisher only conditionally emits items
        has_data = True

        while True:
            disconnected = await req.is_disconnected()
            if disconnected:
                _log.info(f"Disconnecting client {req.client}")
                break
            # Simulate only sending one response
            if has_data:
                yield dict(data="u can haz the data")
                has_data = False
            await asyncio.sleep(0.9)
        _log.info(f"Disconnected from client {req.client}")

    return EventSourceResponse(event_publisher())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="trace")
