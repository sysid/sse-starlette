import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def broadcasting_example(monkeypatch):
    class FakeFastAPI:
        def get(self, _path):
            return lambda endpoint: endpoint

        post = get

    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = FakeFastAPI
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    example_path = Path(__file__).parents[1] / "examples" / "02_broadcasting.py"
    spec = importlib.util.spec_from_file_location("broadcasting_example", example_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_client_queues_are_bounded(broadcasting_example):
    broadcaster = broadcasting_example.MessageBroadcaster()

    queue = broadcaster.add_client()

    assert queue.maxsize > 0


async def test_slow_client_stream_stops_immediately(broadcasting_example):
    broadcaster = broadcasting_example.MessageBroadcaster(max_queue_size=1)
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()
    assert stream.queue is not None

    await broadcaster.broadcast("buffered")
    await broadcaster.broadcast("triggers eviction")

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.1)

    assert broadcaster.client_count == 0


async def test_cancelled_stream_removes_client(broadcasting_example):
    broadcaster = broadcasting_example.MessageBroadcaster()
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()

    next_event = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    next_event.cancel()

    with pytest.raises(asyncio.CancelledError):
        await next_event

    assert broadcaster.client_count == 0
