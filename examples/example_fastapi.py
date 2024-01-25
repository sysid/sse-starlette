import asyncio
import logging

import uvicorn
from fastapi import FastAPI
from starlette.requests import Request

from sse_starlette.sse import EventSourceResponse

_log = logging.getLogger(__name__)
log_fmt = r"%(asctime)-15s %(levelname)s %(name)s %(funcName)s:%(lineno)d %(message)s"
datefmt = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(format=log_fmt, level=logging.DEBUG, datefmt=datefmt)

app = FastAPI()


@app.get("/endless")
async def endless(req: Request):
    """Simulates and endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise, there will be dangling tasks preventing proper shutdown.
    """

    async def event_publisher():
        i = 0

        try:
            while True:
                # yield dict(id=..., event=..., data=...)
                i += 1
                yield dict(data=i)
                await asyncio.sleep(0.9)
        except asyncio.CancelledError as e:
            _log.info(f"Disconnected from client (via refresh/close) {req.client}")
            # Do any other cleanup, if any
            raise e

    return EventSourceResponse(event_publisher())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="trace", log_config=None)  # type: ignore
