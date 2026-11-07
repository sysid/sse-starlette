"""Issue #217: the shielded aclose() after an interrupted send must have a deadline.

A generator whose ``finally`` gets stuck used to keep the response open forever,
because an anyio shield cannot be cancelled from outside.

The stuck cleanups below sleep for a finite STUCK_SECONDS rather than forever. If the
deadline regresses, nothing outside the shield can stop them (``fail_after`` included),
so a ``sleep_forever`` would block CI instead of failing the test.
"""

import inspect
import logging

import anyio
import pytest
from starlette.background import BackgroundTask

from sse_starlette.sse import EventSourceResponse, SendTimeoutError

STUCK_SECONDS = 3
HTTP_SCOPE = {"type": "http", "method": "GET", "headers": []}


def _deadline_warnings(caplog):
    return [
        record
        for record in caplog.records
        if record.name == "sse_starlette.sse"
        and record.levelno == logging.WARNING
        and "cleanup" in record.getMessage()
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "interruption", ["disconnect", "shutdown", "cancel", "send_error", "timeout"]
)
async def test_send_whenInterruptedAndCleanupStuck_thenDeadlineCancelsCleanup(
    interruption, monkeypatch, caplog
):
    send_started = anyio.Event()
    events = []
    send_error = OSError("connection closed")

    async def event_publisher():
        try:
            yield {"data": "first event"}
        finally:
            try:
                await anyio.sleep(STUCK_SECONDS)
                events.append("cleanup ran to the end")
            except anyio.get_cancelled_exc_class():
                events.append("cleanup cancelled")
                raise

    # Keep a reference so garbage collection cannot hide a missing close.
    publisher = event_publisher()
    response = EventSourceResponse(
        publisher,
        ping=0,
        send_timeout=0.01 if interruption == "timeout" else None,
        cleanup_timeout=0.05,
        background=BackgroundTask(lambda: events.append("background")),
    )
    outer_scope = anyio.CancelScope()

    async def send(message):
        if message["type"] == "http.response.body":
            send_started.set()
            if interruption == "send_error":
                raise send_error
            await anyio.sleep_forever()

    async def receive():
        await send_started.wait()
        if interruption == "disconnect":
            return {"type": "http.disconnect"}
        if interruption == "cancel":
            outer_scope.cancel()
        await anyio.sleep_forever()

    async def wait_for_exit():
        await send_started.wait()
        if interruption != "shutdown":
            await anyio.sleep_forever()

    monkeypatch.setattr(response, "_listen_for_exit_signal", wait_for_exit)

    with anyio.fail_after(1), outer_scope:
        if interruption == "send_error":
            with pytest.raises(OSError) as exc_info:
                await response(HTTP_SCOPE, receive, send)
            assert exc_info.value is send_error
        elif interruption == "timeout":
            with pytest.raises(SendTimeoutError):
                await response(HTTP_SCOPE, receive, send)
        else:
            await response(HTTP_SCOPE, receive, send)

    expected = ["cleanup cancelled"]
    if interruption in ("disconnect", "shutdown"):
        expected.append("background")
    assert events == expected
    if interruption == "cancel":
        assert outer_scope.cancelled_caught
    assert len(_deadline_warnings(caplog)) == 1


@pytest.mark.anyio
async def test_stream_whenEncodingFailsAndCleanupStuck_thenDeadlineCancelsCleanup(
    caplog,
):
    events = []

    async def event_publisher():
        try:
            yield {"bogus_field": 1}
        finally:
            try:
                await anyio.sleep(STUCK_SECONDS)
                events.append("cleanup ran to the end")
            except anyio.get_cancelled_exc_class():
                events.append("cleanup cancelled")
                raise

    publisher = event_publisher()
    response = EventSourceResponse(publisher, ping=0, cleanup_timeout=0.05)

    async def send(message):
        pass

    async def receive():
        await anyio.sleep_forever()

    with anyio.fail_after(1):
        with pytest.raises(TypeError, match="bogus_field"):
            await response(HTTP_SCOPE, receive, send)

    assert events == ["cleanup cancelled"]
    assert len(_deadline_warnings(caplog)) == 1


@pytest.mark.anyio
async def test_send_whenCleanupSwallowsDeadlineCancellation_thenStillWarns(caplog):
    """The cleanup was cut short, so stay loud even if the generator hides that."""

    async def event_publisher():
        try:
            yield {"data": "first event"}
        finally:
            try:
                await anyio.sleep(STUCK_SECONDS)
            except anyio.get_cancelled_exc_class():
                pass

    publisher = event_publisher()
    response = EventSourceResponse(publisher, ping=0, cleanup_timeout=0.05)
    send_started = anyio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            send_started.set()
            await anyio.sleep_forever()

    async def receive():
        await send_started.wait()
        return {"type": "http.disconnect"}

    with anyio.fail_after(1):
        await response(HTTP_SCOPE, receive, send)

    assert len(_deadline_warnings(caplog)) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_timeout", [None, 0.5])
async def test_send_whenCleanupFinishesInTime_thenCompletesWithoutWarning(
    cleanup_timeout, caplog
):
    events = []

    async def event_publisher():
        try:
            yield {"data": "first event"}
        finally:
            await anyio.sleep(0.05)
            events.append("cleanup ran to the end")

    publisher = event_publisher()
    response = EventSourceResponse(publisher, ping=0, cleanup_timeout=cleanup_timeout)
    send_started = anyio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            send_started.set()
            await anyio.sleep_forever()

    async def receive():
        await send_started.wait()
        return {"type": "http.disconnect"}

    with anyio.fail_after(1):
        await response(HTTP_SCOPE, receive, send)

    assert events == ["cleanup ran to the end"]
    assert _deadline_warnings(caplog) == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "cleanup_awaits, expected_events",
    [(True, ["cleanup cancelled"]), (False, ["synchronous cleanup ran"])],
)
async def test_send_whenCleanupTimeoutIsZero_thenOnlySynchronousCleanupRuns(
    cleanup_awaits, expected_events
):
    """Zero gives the same budget as a cancellation while awaiting the next item."""
    events = []

    async def event_publisher():
        try:
            yield {"data": "first event"}
        finally:
            if cleanup_awaits:
                try:
                    await anyio.sleep(STUCK_SECONDS)
                except anyio.get_cancelled_exc_class():
                    events.append("cleanup cancelled")
                    raise
            else:
                events.append("synchronous cleanup ran")

    publisher = event_publisher()
    response = EventSourceResponse(publisher, ping=0, cleanup_timeout=0)
    send_started = anyio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            send_started.set()
            await anyio.sleep_forever()

    async def receive():
        await send_started.wait()
        return {"type": "http.disconnect"}

    with anyio.fail_after(1):
        await response(HTTP_SCOPE, receive, send)

    assert events == expected_events


def test_cleanupTimeout_whenOmitted_thenDefaultsToFiniteDeadline():
    default = inspect.signature(EventSourceResponse).parameters["cleanup_timeout"]

    assert default.default == EventSourceResponse.DEFAULT_CLEANUP_TIMEOUT
    assert 0 < EventSourceResponse.DEFAULT_CLEANUP_TIMEOUT < float("inf")


def test_cleanupTimeout_whenNegative_thenRaisesValueError():
    with pytest.raises(ValueError, match=r"cleanup_timeout must be >= 0"):
        EventSourceResponse(iter(()), cleanup_timeout=-1)


@pytest.mark.anyio
@pytest.mark.parametrize("interruption", ["disconnect", "shutdown"])
async def test_closingFrame_whenSendStalls_thenInterruptionEndsResponse(
    interruption, monkeypatch
):
    """#217's other site: the closing frame needs no deadline because it has no shield."""
    closing_frame_started = anyio.Event()
    events = []

    async def event_publisher():
        yield {"data": "only event"}

    response = EventSourceResponse(
        event_publisher(),
        ping=0,
        background=BackgroundTask(lambda: events.append("background")),
    )

    async def send(message):
        if message["type"] == "http.response.body" and not message["more_body"]:
            closing_frame_started.set()
            await anyio.sleep_forever()

    async def receive():
        await closing_frame_started.wait()
        if interruption == "disconnect":
            return {"type": "http.disconnect"}
        await anyio.sleep_forever()

    async def wait_for_exit():
        await closing_frame_started.wait()
        if interruption != "shutdown":
            await anyio.sleep_forever()

    monkeypatch.setattr(response, "_listen_for_exit_signal", wait_for_exit)

    with anyio.fail_after(1):
        await response(HTTP_SCOPE, receive, send)

    assert events == ["background"]
