# PYTHONPATH=. uvicorn examples.load_test:app
# curl http://localhost:8000/stream | pv --line-mode --average-rate > /dev/null

import uvicorn
import json
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse, EventSourceResponseNoPing
from sse_starlette.sse2 import EventSourceResponse2

position = (
    json.dumps(
        {
            "position_timestamp": "2023-09-19T11:25:35.286Z",
            "x": 0,
            "y": 0,
            "z": 0,
            "a": 0,
            "b": 0,
            "c": 0,
            # some more fields
        }
    )
    + "\n"
)
positions = [position] * 500

sse_clients = 0

app = FastAPI()


@app.get("/stream")
async def message_stream(request: Request):
    async def event_generator():
        global sse_clients
        sse_clients += 1
        print(f"{sse_clients} sse clients connected", flush=True)
        while True:
            # If client closes connection, stop sending events
            if await request.is_disconnected():
                break

            for p in positions:
                yield p

    # return EventSourceResponse(event_generator())
    # return EventSourceResponse2(event_generator())
    return EventSourceResponseNoPing(event_generator())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error", log_config=None)  # type: ignore
