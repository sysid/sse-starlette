import asyncio

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from sse_starlette.sse import EventSourceResponse, ServerSentEvent

"""
This examples demonstrates how to use a comment as a ping instead of sending
a dedicated event type 'ping'.
"""

app = FastAPI(title=__name__)
router = APIRouter(prefix="/sse")


async def numbers(minimum, maximum):
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(1)
        yield f"You\r\ncan see me and I'm the {i}"


@router.get("")
async def handle():
    generator = numbers(1, 100)
    return EventSourceResponse(
        generator,
        headers={"Server": "nini"},
        ping=5,
        ping_message_factory=lambda: ServerSentEvent(**{"comment": "You can't see\r\nthis ping"}),
    )


app.include_router(router)
app.mount("/", StaticFiles(directory="./"))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
