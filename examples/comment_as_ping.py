import asyncio

from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles

from sse_starlette.sse import EventSourceResponse

app = FastAPI(title=__name__)
router = APIRouter(prefix="/sse")


async def numbers(minimum, maximum):
    for i in range(minimum, maximum + 1):
        yield {"comment": "You can't see\r\nme"}
        await asyncio.sleep(1)
        yield f"You\r\ncan see me and I'm the {i}"


@router.get("")
async def handle():
    generator = numbers(1, 100)
    return EventSourceResponse(generator, headers={"Server": "nini"})


app.include_router(router)
app.mount("/", StaticFiles(directory="./statics"))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
