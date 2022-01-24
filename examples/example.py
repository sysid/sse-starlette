import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from sse_starlette.sse import EventSourceResponse

# unpatch_uvicorn_signal_handler()  # if you want to rollback monkeypatching of uvcorn signal-handler

_log = logging.getLogger(__name__)
log_fmt = r"%(asctime)-15s %(levelname)s %(name)s %(funcName)s:%(lineno)d %(message)s"
datefmt = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(format=log_fmt, level=logging.DEBUG, datefmt=datefmt)

html_sse = """
    <html>
    <body>
        <script>
            var evtSource = new EventSource("/numbers");
            console.log("evtSource: ", evtSource);
            evtSource.onmessage = function(e) {
                document.getElementById('response').innerText = e.data;
                console.log(e);
                if (e.data == 20) {
                    console.log("Closing connection after 20 numbers.")
                    evtSource.close()
                }
            }
        </script>
        <h1>Response from server:</h1>
        <div id="response"></div>
    </body>
</html>
"""


async def numbers(minimum, maximum):
    """Simulates and limited stream"""
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(0.9)
        yield dict(data=i)


async def endless(req: Request):
    """Simulates and endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise, there will be dangling tasks preventing proper shutdown.
    """

    async def event_publisher():
        i = 0
        try:
            while True:
                # yield dict(id=..., event=..., data=...)
                i += 1
                yield dict(data=i)
                await asyncio.sleep(0.9)
        except asyncio.CancelledError as e:
            _log.info(f"Disconnected from client (via refresh/close) {req.client}")
            # Do any other cleanup, if any
            raise e

    return EventSourceResponse(event_publisher())


async def sse(request):
    generator = numbers(1, 25)
    return EventSourceResponse(generator)


async def home(req: Request):
    return HTMLResponse(html_sse)


routes = [
    Route("/", endpoint=home),
    Route("/numbers", endpoint=sse),
    Route("/endless", endpoint=endless),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="trace", log_config=None)  # type: ignore
