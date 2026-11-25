"""Exercise the runnable connection-limit example, not README snippets."""

import asyncio
import importlib

import pytest

example = importlib.import_module("examples.08_connection_limits")


@pytest.mark.parametrize("ending", ["complete", "disconnect", "cancel"])
async def test_limit_covers_streaming_and_releases_permit(monkeypatch, ending):
    finish = asyncio.Event()
    disconnected = [asyncio.Event(), asyncio.Event()]
    started = [asyncio.Event(), asyncio.Event()]

    async def events():
        yield {"data": "synthetic event"}
        await finish.wait()

    async def run(response, index):
        async def receive():
            await disconnected[index].wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                started[index].set()

        await response({"type": "http", "method": "GET"}, receive, send)

    monkeypatch.setattr(example, "generate_events", events)
    limiter = example.ConnectionLimiter(max_connections=1)
    responses = [await limiter.limited_endpoint(None) for _ in range(2)]
    tasks = []
    try:
        tasks.append(asyncio.create_task(run(responses[0], 0)))
        await asyncio.wait_for(started[0].wait(), 1)
        tasks.append(asyncio.create_task(run(responses[1], 1)))
        # Give the second response time to start if the permit is released early.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(started[1].wait(), 0.05)
        assert not tasks[1].done()

        if ending == "disconnect":
            disconnected[0].set()
            await asyncio.wait_for(tasks[0], 1)
        elif ending == "cancel":
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
        else:
            finish.set()
            await asyncio.wait_for(tasks[0], 1)

        await asyncio.wait_for(started[1].wait(), 1)
        finish.set()
        await asyncio.wait_for(tasks[1], 1)
        assert not limiter.semaphore.locked()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
