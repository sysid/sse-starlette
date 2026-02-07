import asyncio
import logging
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi import Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

"""
  Native Starlette StreamingResponse equivalent of issue164.py.
  Baseline to check whether hang-on-shutdown is specific to sse-starlette
  or also affects vanilla Starlette streaming with BaseHTTPMiddleware.

  uv run uvicorn tests.experimentation.issue164_native:app --reload

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


async def generate_endless_stream(request: Request) -> AsyncGenerator[str, None]:
    """Generate endless numbered events with proper cleanup on client disconnect."""
    counter = 0
    try:
        while True:
            counter += 1
            yield f"id: {counter}\ndata: Event #{counter}\n\n"
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info(f"Client disconnected after receiving {counter} events")
        raise


app = FastAPI()

# When this line is active, connection persists on server shutdown
app.middleware("http")(LoggingMiddleware())


@app.get("/endless")
async def fastapi_endless_endpoint(request: Request) -> StreamingResponse:
    """FastAPI endpoint that streams endless events."""
    return StreamingResponse(
        generate_endless_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
