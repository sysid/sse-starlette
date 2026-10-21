import anyio
import pytest
from starlette.background import BackgroundTask

from sse_starlette import EventSourceResponse


class UnreadAsyncIterator:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise AssertionError("HEAD must not consume the async stream")


class UnreadSyncIterator:
    def __iter__(self):
        return self

    def __next__(self):
        raise AssertionError("HEAD must not consume the sync stream")


@pytest.mark.parametrize("method", ["HEAD", "head"])
@pytest.mark.parametrize("content", [UnreadAsyncIterator, UnreadSyncIterator])
async def test_head_completes_without_starting_stream(method, content):
    messages = []
    calls = []

    async def send(message):
        messages.append(message)

    async def receive():
        raise AssertionError("HEAD must not wait for a disconnect")

    async def produce():
        calls.append("producer")

    async def background():
        assert messages[-1] == {
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        }
        calls.append("background")

    response = EventSourceResponse(
        content(),
        status_code=202,
        headers={"X-Test": "retained", "Cache-Control": "no-cache"},
        background=BackgroundTask(background),
        data_sender_callable=produce,
    )
    with anyio.fail_after(1):
        await response({"type": "http", "method": method}, receive, send)

    assert messages == [
        {
            "type": "http.response.start",
            "status": 202,
            "headers": response.raw_headers,
        },
        {"type": "http.response.body", "body": b"", "more_body": False},
    ]
    assert dict(response.raw_headers)[b"x-test"] == b"retained"
    assert dict(response.raw_headers)[b"cache-control"] == b"no-cache"
    assert dict(response.raw_headers)[b"content-type"].startswith(b"text/event-stream")
    assert calls == ["background"]
    assert response.active is False


@pytest.mark.parametrize(
    "failed_message", ["http.response.start", "http.response.body"]
)
async def test_head_send_failure_propagates_without_background(failed_message):
    calls = []

    async def send(message):
        if message["type"] == failed_message:
            raise RuntimeError("send failed")

    async def receive():
        raise AssertionError("HEAD must not wait for a disconnect")

    async def background():
        calls.append("background")

    response = EventSourceResponse(
        UnreadAsyncIterator(), background=BackgroundTask(background)
    )
    with pytest.raises(RuntimeError, match="send failed"):
        await response({"type": "http", "method": "HEAD"}, receive, send)
    assert calls == []
