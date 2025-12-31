import asyncio
import itertools
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

"""
https://github.com/sysid/sse-starlette/issues/132

# Run uvicorn
$ uvicorn issue132:app

# Open the app in a browser
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:49184 - "GET /events HTTP/1.1" 200 OK

# Press CTRL+C to stop the server
^CINFO:     Shutting down
INFO:     Waiting for connections to close. (CTRL+C to force quit)
"""

app = FastAPI()


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SSE ASGI tests</title>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <script src="https://unpkg.com/htmx-ext-sse@2.2.2"></script>
  <link rel="stylesheet" href="https://cdn.simplecss.org/simple.min.css">
</head>
<body>
<a hx-ext="sse" sse-connect="/events" sse-swap="message">0</a>
</body>
</html>
"""
    )


@app.get("/events")
async def event_source() -> EventSourceResponse:
    async def event_generator():
        for x in itertools.count():
            yield x
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.main()
    # uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
