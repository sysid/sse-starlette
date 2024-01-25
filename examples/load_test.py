################################################################################
# Load test
# e.g. test for lock contention: https://github.com/sysid/sse-starlette/issues/77
#
# to run it:
# PYTHONPATH=. uvicorn examples.load_test:app
# curl http://localhost:8000/stream | pv --line-mode --average-rate > /dev/null
################################################################################

import json

import uvicorn
from fastapi import FastAPI, Request

from sse_starlette.sse import EventSourceResponse

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
                # fixes socket.send() raised exception, but makes it very slow!!
                if await request.is_disconnected():
                    break
                yield p

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error", log_config=None)  # type: ignore
