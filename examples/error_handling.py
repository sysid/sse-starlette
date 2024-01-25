import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from starlette.staticfiles import StaticFiles

from sse_starlette import EventSourceResponse, ServerSentEvent

"""
This example shows how to handle errors in the generator function.

The error message can be processed on the client-side to handle the error gracefully.
Note the use of return after yielding the error message.
This will stop the generator from continuing after an error occurs.
"""

app = FastAPI(title=__name__)
router = APIRouter(prefix="/sse")


async def numbers(minimum: int, maximum: int) -> Any:
    for i in range(minimum, maximum + 1):
        try:
            if i == 3:
                raise HTTPException(400)
        except HTTPException as e:
            yield ServerSentEvent(**{"data": str(e)})
            return
        else:
            await asyncio.sleep(0.9)
            yield dict(data=i)


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
