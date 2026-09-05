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
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_addClient_whenCalled_thenQueueIsBounded(broadcasting_example):
    broadcaster = broadcasting_example.MessageBroadcaster()

    queue = broadcaster.add_client()

    assert queue.maxsize > 0


async def test_broadcast_whenClientQueueFull_thenSlowClientEvictedAndPeerUnaffected(
    broadcasting_example,
):
    # Both clients get a queue of size 1. The healthy client keeps consuming,
    # the slow client never does, so only the slow queue overflows.
    broadcaster = broadcasting_example.MessageBroadcaster(max_queue_size=1)
    slow_stream = broadcaster.create_stream(ConnectedRequest())
    slow_stream.__aiter__()
    healthy_stream = broadcaster.create_stream(ConnectedRequest())
    healthy_stream.__aiter__()
    assert broadcaster.client_count == 2

    await broadcaster.broadcast("first")
    first_event = await anext(healthy_stream)
    assert first_event.data == "first"

    await broadcaster.broadcast("second")

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(slow_stream), timeout=0.1)
    second_event = await asyncio.wait_for(anext(healthy_stream), timeout=0.1)
    assert second_event.data == "second"
    assert broadcaster.client_count == 1


async def test_anext_whenCancelled_thenClientRemoved(broadcasting_example):
    broadcaster = broadcasting_example.MessageBroadcaster()
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()

    next_event = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    next_event.cancel()

    with pytest.raises(asyncio.CancelledError):
        await next_event

    assert broadcaster.client_count == 0


async def test_aclose_whenCalled_thenClientRemoved(broadcasting_example):
    # EventSourceResponse calls aclose() on the body iterator after a send
    # timeout; without it the evicted client would stay registered.
    broadcaster = broadcasting_example.MessageBroadcaster()
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()
    assert broadcaster.client_count == 1

    await stream.aclose()

    assert broadcaster.client_count == 0


async def test_anext_whenCalledAfterAclose_thenRaisesStopAsyncIteration(
    broadcasting_example,
):
    # A closed stream must be terminal like a real async generator. Without a
    # closed flag __anext__ awaits a queue nobody feeds any more and parks
    # forever, because aclose() unregistered it from the broadcaster.
    broadcaster = broadcasting_example.MessageBroadcaster()
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()
    await stream.aclose()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.1)


async def test_aiter_whenCalledAfterAclose_thenStreamStaysUnregistered(
    broadcasting_example,
):
    # Re-entering __aiter__ on a closed stream would hand out a second queue
    # and register it, resurrecting a client that already went away.
    broadcaster = broadcasting_example.MessageBroadcaster()
    stream = broadcaster.create_stream(ConnectedRequest())
    stream.__aiter__()
    await stream.aclose()

    stream.__aiter__()

    assert broadcaster.client_count == 0


@pytest.mark.parametrize("max_queue_size", [0, -1])
def test_init_whenMaxQueueSizeNotPositive_thenRaisesValueError(
    broadcasting_example, max_queue_size
):
    # maxsize=0 means unbounded in asyncio, which is the bug this example had.
    with pytest.raises(ValueError, match="max_queue_size"):
        broadcasting_example.MessageBroadcaster(max_queue_size=max_queue_size)
