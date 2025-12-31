import asyncio
from typing import Optional

from fastapi import Depends, FastAPI
from starlette import status

from sse_starlette import EventSourceResponse, ServerSentEvent

"""
This example shows how to use a stream to push messages to a single client

Remark:
Lazy initialization of the queue for safe handling of initializing asyncio.Queue()
outside of an async context (it calls asyncio.get_event_loop() internally).
This is not an issue for python > 3.9 any more.

Example Client Usage:
# This command will stay connected and display all incoming messages
curl -N http://127.0.0.1:8000/sse

# In a separate terminal, send a message
curl -X POST "http://127.0.0.1:8000/message?message=Hello%20World" -H "accept: application/json"

# Send a message with quotes and spaces
curl -X POST "http://127.0.0.1:8000/message?message=This%20is%20a%20test%20message" -H "accept: application/json"

# Send a message with special characters
curl -X POST "http://127.0.0.1:8000/message?message=Special%20chars:%20%21%40%23%24%25%5E%26%2A%28%29" -H "accept: application/json"

# Send multiple messages in quick succession
for i in {1..5}; do
    curl -X POST "http://127.0.0.1:8000/message?message=Message%20number%20$i" -H "accept: application/json"
    sleep 0.5
done
"""


class Stream:
    def __init__(self) -> None:
        self._queue: Optional[asyncio.Queue[ServerSentEvent]] = None

    @property
    def queue(self) -> asyncio.Queue[ServerSentEvent]:
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
    await stream.asend(ServerSentEvent(data=message))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="trace")
