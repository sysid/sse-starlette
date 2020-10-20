import asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from sse_starlette.sse import EventSourceResponse

from uvicorn.config import logger as _log

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
    """ Simulates and limited stream """
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(0.9)
        yield dict(data=i)


async def endless(req: Request):
    """Simulates and endless stream

    In case of server shutdown the running task has to be stopped via signal handler in order
    to enable proper server shutdown. Otherwise there will be dangling tasks preventing proper shutdown.
    """

    async def event_publisher():
        i = 0
        try:
            while True:
                disconnected = await req.is_disconnected()
                if disconnected:
                    _log.info(f"Disconnecting client {req.client}")
                    break
                # yield dict(id=..., event=..., data=...)
                i += 1
                yield dict(data=i)
                await asyncio.sleep(0.9)
            _log.info(f"Disconnected from client {req.client}")
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
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="trace")
