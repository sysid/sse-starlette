import logging
from functools import partial

import anyio
import trio
import uvicorn
from anyio.streams.memory import MemoryObjectSendStream
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
    """Simulates an endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise, there will be dangling tasks preventing proper shutdown.
    """
    send_chan, recv_chan = anyio.create_memory_object_stream(10)
    async def event_publisher(inner_send_chan: MemoryObjectSendStream):
        async with inner_send_chan:
            try: 
                i = 0
                while True:
                    i += 1
                    await inner_send_chan.send(dict(data=i))
                    await anyio.sleep(1.0)
            except anyio.get_cancelled_exc_class() as e:
                _log.info(f"Disconnected from client (via refresh/close) {req.client}")
                with anyio.move_on_after(1, shield=True):
                    await inner_send_chan.send(dict(closing=True))
                    raise e

    return EventSourceResponse(recv_chan, data_sender_callable=partial(event_publisher, send_chan))



@app.get("/endless-trio")
async def endless_trio(req: Request):
    """Simulates an endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise, there will be dangling tasks preventing proper shutdown.
    """
    raise Exception("Trio is not compatible with uvicorn, this code is for example purposes")

    send_chan, recv_chan = trio.open_memory_channel(10)
    async def event_publisher(inner_send_chan: trio.MemorySendChannel):
        async with inner_send_chan:
            try: 
                i = 0
                while True:
                    i += 1
                    await inner_send_chan.send(dict(data=i))
                    await trio.sleep(1.0)
            except trio.Cancelled as e:
                _log.info(f"Disconnected from client (via refresh/close) {req.client}")
                with anyio.move_on_after(1, shield=True):
                    # This may not make it 
                    await inner_send_chan.send(dict(closing=True))
                    raise e

    return EventSourceResponse(recv_chan, data_sender_callable=partial(event_publisher, send_chan))



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="trace", log_config=None)  # type: ignore
