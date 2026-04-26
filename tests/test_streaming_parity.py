"""Parity tests vs Starlette's StreamingResponse.

These cover behaviour we intentionally re-sync from
``starlette.responses.StreamingResponse`` so that ``EventSourceResponse``
remains a drop-in citizen in the Starlette response hierarchy.
"""

from __future__ import annotations

import pytest

from sse_starlette import EventSourceResponse


@pytest.mark.asyncio
async def test_call_when_generatorRaises_then_bareExceptionPropagates():
    """A user-generator exception must not surface as an ExceptionGroup.

    StreamingResponse uses ``collapse_excgroups()`` around its task group so
    middleware sees the bare exception. EventSourceResponse must do the same.
    """

    async def boom():
        yield {"data": "first"}
        raise RuntimeError("boom")

    response = EventSourceResponse(boom(), ping=1000)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        # Block forever — the generator's exception should end the response
        # before any disconnect is needed.
        import anyio

        await anyio.sleep_forever()

    scope = {"type": "http", "method": "GET", "headers": []}

    with pytest.raises(RuntimeError, match="boom"):
        await response(scope, receive, send)


@pytest.mark.asyncio
async def test_call_whenWebsocketScope_thenSendIsWrappedForDenial():
    """Streaming responses must be usable as WebSocket denial responses.

    Starlette wraps ``send`` so message types become ``websocket.http.response.*``.
    """

    async def gen():
        yield b"denied"

    response = EventSourceResponse(gen(), ping=1000)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - never awaited on WS denial path
        import anyio

        await anyio.sleep_forever()

    scope = {"type": "websocket", "headers": []}

    await response(scope, receive, send)

    types = [m["type"] for m in sent]
    assert types, "expected at least one message"
    for t in types:
        assert t.startswith("websocket."), f"unexpected message type: {t}"
    assert "websocket.http.response.start" in types
    assert "websocket.http.response.body" in types
