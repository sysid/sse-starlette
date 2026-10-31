"""Regression coverage for the exact README connection-limit example.

Uses stdlib unittest.IsolatedAsyncioTestCase, also collectable by pytest.
Run with python -m unittest. Set SSE_README_UNDER_TEST to run
against another README snapshot, including the unpatched baseline.
"""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import unittest

from starlette.background import BackgroundTask
from sse_starlette import EventSourceResponse

README = Path(
    os.environ.get(
        "SSE_README_UNDER_TEST", str(Path(__file__).resolve().parents[1] / "README.md")
    )
)
SCOPE = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}


def _limiter(generate_events, max_connections=1):
    blocks = [
        block
        for block in re.findall(r"```python\n(.*?)```", README.read_text(), re.S)
        if "# Connection limits" in block
    ]
    assert len(blocks) == 1, "README must contain one connection-limit example"
    namespace = {
        "asyncio": asyncio,
        "EventSourceResponse": EventSourceResponse,
        "generate_events": generate_events,
    }
    exec(compile(blocks[0], str(README), "exec"), namespace)
    return namespace["ConnectionLimiter"](max_connections=max_connections)


async def _bounded(scenario):
    await asyncio.wait_for(scenario, timeout=3)


async def _finite_events():
    yield {"data": "synthetic test event"}


class SyntheticSendError(OSError):
    pass


class _Call:
    def __init__(self, response, fail_send=False):
        self.response = response
        self.invoked = asyncio.Event()
        self.started = asyncio.Event()
        self.body_sent = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.failure_ready = asyncio.Event()
        self.allow_failure = asyncio.Event()
        self.fail_send = fail_send
        self.messages = []

    async def receive(self):
        await self.disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(self, message):
        self.messages.append(message)
        if message["type"] == "http.response.start":
            self.started.set()
        if message["type"] == "http.response.body" and message.get("body"):
            if self.fail_send:
                self.failure_ready.set()
                await self.allow_failure.wait()
                raise SyntheticSendError("synthetic transport failure")
            self.body_sent.set()

    async def run(self):
        self.invoked.set()
        await self.response(SCOPE, self.receive, self.send)

    async def assert_waiting(self):
        # Let the invoked ASGI call and its scheduled stream task reach send().
        # There are no timer-, network-, or thread-dependent operations here.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not self.started.is_set(), "another response started before permit release"
        assert not self.task.done(), "queued ASGI call must remain pending"


@asynccontextmanager
async def _call(response, **kwargs):
    call = _Call(response, **kwargs)
    call.task = asyncio.create_task(call.run())
    try:
        await call.invoked.wait()
        yield call
    finally:
        if not call.task.done():
            call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)


async def _assert_cancelled(task):
    try:
        await task
    except asyncio.CancelledError:
        return
    raise AssertionError("task did not propagate cancellation")


async def _assert_raises(task, error_type):
    try:
        await task
    except error_type:
        return
    raise AssertionError(f"task did not propagate {error_type.__name__}")


class ReadmeConnectionLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_limit_spans_asgi_execution_not_response_construction(self):
        async def scenario():
            finish = asyncio.Event()
            iterations = []

            async def events():
                iterations.append(True)
                yield {"data": "synthetic test event"}
                await finish.wait()

            limiter = _limiter(events)
            response_one = await limiter.limited_endpoint(None)
            response_two = await limiter.limited_endpoint(None)
            assert iterations == [], "response construction must not start streaming"
            assert not limiter.semaphore.locked(), "construction must not reserve a permit"
            async with _call(response_one) as first:
                await first.body_sent.wait()
                async with _call(response_two) as second:
                    await second.assert_waiting()
                    assert len(iterations) == 1
                    finish.set()
                    await first.task
                    await second.task
                    assert len(iterations) == 2
                    assert second.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_disconnect_releases_permit_for_the_waiting_response(self):
        async def scenario():
            async def events():
                yield {"data": "synthetic test event"}
                await asyncio.Event().wait()

            limiter = _limiter(events)
            async with _call(await limiter.limited_endpoint(None)) as first:
                await first.body_sent.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    first.disconnected.set()
                    await first.task
                    await second.body_sent.wait()
                    second.disconnected.set()
                    await second.task
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_send_error_releases_permit_for_the_waiting_response(self):
        async def scenario():
            limiter = _limiter(_finite_events)
            async with _call(await limiter.limited_endpoint(None), fail_send=True) as first:
                await first.failure_ready.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    first.allow_failure.set()
                    await _assert_raises(first.task, SyntheticSendError)
                    await second.task
                    assert second.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_cancelling_a_queued_response_does_not_release_an_owned_permit(self):
        async def scenario():
            finish = asyncio.Event()

            async def events():
                yield {"data": "synthetic test event"}
                await finish.wait()

            limiter = _limiter(events)
            async with _call(await limiter.limited_endpoint(None)) as first:
                await first.body_sent.wait()
                async with _call(await limiter.limited_endpoint(None)) as cancelled:
                    await cancelled.assert_waiting()
                    cancelled.task.cancel()
                    await _assert_cancelled(cancelled.task)
                    assert not cancelled.started.is_set()
                async with _call(await limiter.limited_endpoint(None)) as third:
                    await third.assert_waiting()
                    finish.set()
                    await first.task
                    await third.task
                    assert third.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_cancelling_an_active_response_releases_its_permit(self):
        async def scenario():
            async def events():
                yield {"data": "synthetic test event"}
                await asyncio.Event().wait()

            limiter = _limiter(events)
            async with _call(await limiter.limited_endpoint(None)) as first:
                await first.body_sent.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    first.task.cancel()
                    await _assert_cancelled(first.task)
                    await second.body_sent.wait()
                    second.disconnected.set()
                    await second.task
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_background_task_keeps_the_permit_until_it_finishes(self):
        async def scenario():
            background_started = asyncio.Event()
            background_finish = asyncio.Event()

            async def background():
                background_started.set()
                await background_finish.wait()

            limiter = _limiter(_finite_events)
            response = await limiter.limited_endpoint(None)
            response.background = BackgroundTask(background)
            async with _call(response) as first:
                await background_started.wait()
                assert any(
                    message["type"] == "http.response.body" and not message.get("more_body")
                    for message in first.messages
                ), "stream must have finished before the background check"
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    background_finish.set()
                    await first.task
                    await second.task
                    assert second.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_background_failure_releases_permit(self):
        async def scenario():
            background_started = asyncio.Event()
            background_finish = asyncio.Event()

            async def background():
                background_started.set()
                await background_finish.wait()
                raise RuntimeError("synthetic background failure")

            limiter = _limiter(_finite_events)
            response = await limiter.limited_endpoint(None)
            response.background = BackgroundTask(background)
            async with _call(response) as first:
                await background_started.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    background_finish.set()
                    await _assert_raises(first.task, RuntimeError)
                    await second.task
                    assert second.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_cancellation_during_background_task_releases_permit(self):
        async def scenario():
            background_started = asyncio.Event()

            async def background():
                background_started.set()
                await asyncio.Event().wait()

            limiter = _limiter(_finite_events)
            response = await limiter.limited_endpoint(None)
            response.background = BackgroundTask(background)
            async with _call(response) as first:
                await background_started.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    first.task.cancel()
                    await _assert_cancelled(first.task)
                    await second.task
                    assert second.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_disconnect_keeps_permit_through_its_background_task(self):
        async def scenario():
            background_started = asyncio.Event()
            background_finish = asyncio.Event()

            async def events():
                yield {"data": "synthetic test event"}
                await asyncio.Event().wait()

            async def background():
                background_started.set()
                await background_finish.wait()

            limiter = _limiter(events)
            response = await limiter.limited_endpoint(None)
            response.background = BackgroundTask(background)
            async with _call(response) as first:
                await first.body_sent.wait()
                first.disconnected.set()
                await background_started.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.assert_waiting()
                    background_finish.set()
                    await first.task
                    await second.body_sent.wait()
                    second.disconnected.set()
                    await second.task
            assert not limiter.semaphore.locked()

        await _bounded(scenario())

    async def test_configured_capacity_admits_two_and_queues_the_third(self):
        async def scenario():
            finish = asyncio.Event()

            async def events():
                yield {"data": "synthetic test event"}
                await finish.wait()

            limiter = _limiter(events, max_connections=2)
            async with _call(await limiter.limited_endpoint(None)) as first:
                await first.body_sent.wait()
                async with _call(await limiter.limited_endpoint(None)) as second:
                    await second.body_sent.wait()
                    async with _call(await limiter.limited_endpoint(None)) as third:
                        await third.assert_waiting()
                        finish.set()
                        await first.task
                        await second.task
                        await third.task
                        assert third.body_sent.is_set()
            assert not limiter.semaphore.locked()

        await _bounded(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
