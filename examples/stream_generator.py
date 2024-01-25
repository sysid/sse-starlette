import asyncio

from fastapi import Depends, FastAPI
from starlette import status

from sse_starlette import EventSourceResponse, ServerSentEvent

"""
This example shows how to use a stream to push messages to a single client
"""

class Stream:
    def __init__(self) -> None:
        self._queue = asyncio.Queue[ServerSentEvent]()

    def __aiter__(self) -> "Stream":
        return self

    async def __anext__(self) -> ServerSentEvent:
        return await self._queue.get()

    async def asend(self, value: ServerSentEvent) -> None:
        await self._queue.put(value)


app = FastAPI()

_stream = Stream()
app.dependency_overrides[Stream] = lambda: _stream


@app.get("/sse")
async def sse(stream: Stream = Depends()) -> EventSourceResponse:
    return EventSourceResponse(stream)


@app.post("/message", status_code=status.HTTP_201_CREATED)
async def send_message(message: str, stream: Stream = Depends()) -> None:
    await stream.asend(
        ServerSentEvent(data=message)
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="trace")
