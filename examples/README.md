# Examples

Runnable examples demonstrating sse-starlette features.

## Prerequisites

- `pip install sse-starlette` (or install from source)
- Most examples need: `pip install fastapi uvicorn`
- Example 03 additionally needs: `pip install sqlalchemy[asyncio] aiosqlite`

## Examples

| Example | Feature | Dependencies |
|---------|---------|-------------|
| [01_basic_sse.py](01_basic_sse.py) | Basic streaming (Starlette + FastAPI), conditional data | fastapi, uvicorn |
| [02_broadcasting.py](02_broadcasting.py) | Multi-client broadcasting via per-client queues | fastapi, uvicorn |
| [03_database_streaming.py](03_database_streaming.py) | Thread-safe DB sessions in SSE generators | fastapi, uvicorn, sqlalchemy, aiosqlite |
| [04_advanced_features.py](04_advanced_features.py) | Custom ping, error handling, separators, headers | fastapi, uvicorn |
| [05_memory_channels.py](05_memory_channels.py) | Memory channels with `data_sender_callable` | uvicorn |
| [06_send_timeout.py](06_send_timeout.py) | Frozen client detection via `send_timeout` | uvicorn |
| [07_cooperative_shutdown.py](07_cooperative_shutdown.py) | Graceful shutdown with farewell events (v3.3.0) | uvicorn |

## Running

Each example declares its dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)). With [uv](https://docs.astral.sh/uv/):

```
uv run examples/01_basic_sse.py
```

Or install dependencies manually and run with Python directly:

```
pip install sse-starlette fastapi uvicorn
python examples/01_basic_sse.py
```

Then test with:

```
curl -N http://localhost:8000/<endpoint>
```

See each file's docstring for specific endpoints and curl commands.
