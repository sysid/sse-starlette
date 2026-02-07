import asyncio
import logging
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi import Request
from starlette.responses import FileResponse

from sse_starlette import EventSourceResponse
from starlette.middleware.base import RequestResponseEndpoint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

"""
  uv run uvicorn tests.experimentation.issue164:app --reload

  Then test the SSE endpoint at http://localhost:8000/endless
  curl -v http://localhost:8000/endless
"""


class LoggingMiddleware:
    async def __call__(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ):
        response = await call_next(request)
        logger.info("Log something...")
        return response


async def generate_endless_stream(request: Request) -> AsyncGenerator[dict, None]:
    """Generate endless numbered events with proper cleanup on client disconnect."""
    counter = 0
    try:
        while True:
            counter += 1
            yield {"data": f"Event #{counter}", "id": str(counter)}
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info(f"Client disconnected after receiving {counter} events")
        raise


app = FastAPI()

# When this line is active, connection persists on server shutdown
app.middleware("http")(LoggingMiddleware())


@app.get("/endless")
async def fastapi_endless_endpoint(request: Request) -> EventSourceResponse:
    """FastAPI endpoint that streams endless events."""
    return EventSourceResponse(generate_endless_stream(request))


@app.get("/")
async def serve_index():
    """Serves the index.html file from the local directory."""
    # Ensure index.html is in the same folder as this script
    return FileResponse("tests/experimentation/issue164/index.html")
