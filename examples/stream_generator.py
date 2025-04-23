import asyncio

from fastapi import Depends, FastAPI
from starlette import status

from sse_starlette import EventSourceResponse, ServerSentEvent

"""
This example shows how to use a stream to push messages to a single client
"""

class Stream:
    def __init__(self) -> None:
        self._queue = None

    @property
    def queue(self):
        if self._queue is None:
            self._queue = asyncio.Queue[ServerSentEvent]()
        return self._queue

    def __aiter__(self) -> "Stream":
        return self

    async def __anext__(self) -> ServerSentEvent:
        return await self.queue.get()

    async def asend(self, value: ServerSentEvent) -> None:
        await self.queue.put(value)


app = FastAPI()

_stream = Stream()


@app.get("/sse")
async def sse(stream: Stream = Depends(lambda: _stream)) -> EventSourceResponse:
    return EventSourceResponse(stream)


@app.post("/message", status_code=status.HTTP_201_CREATED)
async def send_message(message: str, stream: Stream = Depends(lambda: _stream)) -> None:
    await stream.asend(
        ServerSentEvent(data=message)
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="trace")
