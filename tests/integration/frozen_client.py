"""
https://github.com/sysid/sse-starlette/issues/89
Server Simulation:
Run with: uvicorn tests.integration.frozen_client:app

Client Simulation:
% curl -s -N localhost:8000/events > /dev/null
^Z (suspend process -> no consumption of messages but connection alive)

Measure resource consumption:
connections: lsof -i :8000
buffers: netstat -m
"""
import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from sse_starlette import EventSourceResponse


async def events(request):
    async def _event_generator():
        try:
            i = 0
            while True:
                i += 1
                if i % 100 == 0:
                    print(i)
                yield dict(data={i: " " * 4096})
                await anyio.sleep(0.001)
        finally:
            print("disconnected")

    return EventSourceResponse(_event_generator(), send_timeout=10)


app = Starlette(
    debug=True,
    routes=[
        Route("/events", events),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="trace", log_config=None)  # type: ignore
