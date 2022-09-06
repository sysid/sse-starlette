# Server Sent Events for [Starlette](https://github.com/encode/starlette) and [FastAPI](https://fastapi.tiangolo.com/)

[![PyPI Version][pypi-image]][pypi-url]
[![Build Status][build-image]][build-url]
[![Code Coverage][coverage-image]][coverage-url]

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

Be aware that for proper server shutdown your application must stop all
running tasks (generators). Otherwise you might experience the following warnings
at shutdown: `Waiting for background tasks to complete. (CTRL+C to force quit)`.

Client disconnects need to be handled in your Request handler (see example.py):
```python
async def endless(req: Request):
    async def event_publisher():
        i = 0
        try:
          while True:
              i += 1
              yield dict(data=i)
              await asyncio.sleep(0.2)
        except asyncio.CancelledError as e:
          _log.info(f"Disconnected from client (via refresh/close) {req.client}")
          # Do any other cleanup, if any
          raise e
    return EventSourceResponse(event_publisher())
```

Run the tests:
```python
make test
```

## Special use cases
### Fan out Proxies
Fan out proxies usually rely on response being cacheable. To support that, you can set the value of `Cache-Control`.
For example:
```python
return EventSourceResponse(
        generator(), headers={"Cache-Control": "public, max-age=29"}
    )
```

## Changelog
[CHANGELOG.md](https://github.com/sysid/sse-starlette/blob/master/CHANGELOG.md)

<!-- Badges -->

[pypi-image]: https://badge.fury.io/py/sse-starlette.svg
[pypi-url]: https://pypi.org/project/sse-starlette/
[build-image]: https://github.com/sysid/sse-starlette/actions/workflows/build.yml/badge.svg
[build-url]: https://github.com/sysid/sse-starlette/actions/workflows/build.yml
[coverage-image]: https://codecov.io/gh/sysid/sse-starlette/branch/master/graph/badge.svg
[coverage-url]: https://codecov.io/gh/sysid/sse-starlette
