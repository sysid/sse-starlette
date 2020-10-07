# Server Sent Events for [Starlette](https://github.com/encode/starlette)

Background: https://sysid.github.io/sse/

Installation:

```shell
pip install sse-starlette
```

Usage:

```python
import asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from sse_starlette.sse import EventSourceResponse

async def numbers(minimum, maximum):
    for i in range(minimum, maximum + 1):
        await asyncio.sleep(0.9)
        yield dict(data=i)

async def sse(request):
    generator = numbers(1, 5)
    return EventSourceResponse(generator)

routes = [
    Route("/", endpoint=sse)
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level='info')
```

Output:  
![output](output.png)

**Caveat:** SSE streaming does not work in combination with [GZipMiddleware](https://github.com/encode/starlette/issues/20#issuecomment-704106436).

Be aware that for proper server shutdown the application must stop all
running tasks (generators). Otherwise you might experience the following warnings
at shutdown: `Waiting for background tasks to complete. (CTRL+C to force quit)`.

Client disconnects need to be handled in the Request handler (see example.py):
```python
async def endless(req: Request):
    async def event_publisher():
        i = 0
        while True:
            disconnected = await req.is_disconnected()
            if disconnected:
                _log.info(f"Disconnecting client {req.client}")
                break
            i += 1
            yield dict(data=i)
            await asyncio.sleep(0.2)
        _log.info(f"Disconnected from client {req.client}")

    return EventSourceResponse(event_publisher())
```

Run the tests:
```python
make test
```
