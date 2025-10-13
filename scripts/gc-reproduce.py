import asyncio
import gc
from collections import defaultdict

import uvicorn
from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def fake_stream_response(num_chunks: int):
    """Generate fake streaming responses like the original."""
    for i in range(num_chunks):
        await asyncio.sleep(0.1)

        chunk = {"data": f"chunk_{i}"}
        yield chunk


async def stream_it(
    request: Request,
):
    response = fake_stream_response(10)
    return EventSourceResponse(response)


def get_objects(request: Request) -> dict[str, int]:
    class_name = request.query_params.get("class_name", "")
    if not class_name:
        return JSONResponse({"error": "class_name is required"})

    result: dict[str, int] = defaultdict(lambda: 0)
    for obj in gc.get_objects():
        if obj.__class__.__name__.lower() == class_name.lower():
            result["count"] += 1
            for ref in gc.get_referrers(obj):
                result[f"ref-{ref.__class__.__name__}"] += 1

    return JSONResponse(result)


# Define the routes
routes = [
    Route("/stream", methods=["POST"], endpoint=stream_it),
    Route("/objects", endpoint=get_objects),
]

# Create the Starlette application instance
app = Starlette(debug=True, routes=routes)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
