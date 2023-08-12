import asyncio
import logging

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sse_starlette import EventSourceResponse
from sse_starlette.sse import AppStatus
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

_log = logging.getLogger(__name__)
log_fmt = r"%(asctime)-15s %(levelname)s %(name)s %(funcName)s:%(lineno)d %(message)s"
datefmt = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(format=log_fmt, level=logging.DEBUG, datefmt=datefmt)

logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.INFO)


@pytest.fixture
def anyio_backend():
    """Exclude trio from tests"""
    return "asyncio"


@pytest.fixture
async def app():
    async def startup():
        _log.debug("Starting up")

    async def shutdown():
        _log.debug("Shutting down")

    async def home():
        return PlainTextResponse("Hello, world!")

    async def endless(req: Request):
        async def event_publisher():
            i = 0
            try:
                while True:  # i <= 20:
                    # yield dict(id=..., event=..., data=...)
                    i += 1
                    print(f"Sending {i}")
                    yield dict(data=i)
                    await asyncio.sleep(0.3)
            except asyncio.CancelledError as e:
                _log.info(f"Disconnected from client (via refresh/close) {req.client}")
                # Do any other cleanup, if any
                raise e

        return EventSourceResponse(event_publisher())

    app = Starlette(
        routes=[Route("/", home), Route("/endless", endpoint=endless)],
        on_startup=[startup],
        on_shutdown=[shutdown],
    )

    async with LifespanManager(app):
        _log.info("We're in!")
        yield app
        _log.info("We're out!")


@pytest.fixture
def reset_appstatus_event():
    # avoid: RuntimeError: <asyncio.locks.Event object at 0x1046a0a30 [unset]> is bound to a different event loop
    AppStatus.should_exit_event = None


@pytest.fixture
async def httpx_client(reset_appstatus_event, app):
    async with httpx.AsyncClient(app=app, base_url="http://localhost:8000") as client:
        _log.info("Yielding Client")
        yield client


@pytest.fixture
def client(reset_appstatus_event, app):
    with TestClient(app=app, base_url="http://localhost:8000") as client:
        print("Yielding Client")
        yield client
