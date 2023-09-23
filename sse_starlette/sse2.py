import io
import logging
import re
from datetime import datetime
from functools import partial
from typing import Any, AsyncIterable, Callable, Coroutine, Dict, Optional, Union

import anyio
from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from sse_starlette import ServerSentEvent
from sse_starlette.sse import AppStatus, ensure_bytes

_log = logging.getLogger(__name__)


class EventSourceResponse2(Response):
    """Implements the ServerSentEvent Protocol:
    https://www.w3.org/TR/2009/WD-eventsource-20090421/

    Responses must not be compressed by middleware in order to work.
    implementation based on Starlette StreamingResponse
    """

    # noinspection PyMissingConstructor
    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Optional[Dict] = None,
        media_type: str = "text/event-stream",
        background: Optional[BackgroundTask] = None,
        sep: Optional[str] = None,
        data_sender_callable: Optional[
            Callable[[], Coroutine[None, None, None]]
        ] = None,
    ) -> None:
        if sep is not None and sep not in ["\r\n", "\r", "\n"]:
            raise ValueError(f"sep must be one of: \\r\\n, \\r, \\n, got: {sep}")
        self.sep = sep
        if isinstance(content, AsyncIterable):
            self.body_iterator = (
                content
            )  # type: AsyncIterable[Union[Any,dict,ServerSentEvent]]
        else:
            self.body_iterator = iterate_in_threadpool(content)  # type: ignore
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = background  # type: ignore  # follows https://github.com/encode/starlette/blob/master/starlette/responses.py
        self.data_sender_callable = data_sender_callable

        _headers = {}
        if headers is not None:  # pragma: no cover
            _headers.update(headers)

        # mandatory for servers-sent events headers
        # allow cache control header to be set by user to support fan out proxies
        # https://www.fastly.com/blog/server-sent-events-fastly
        _headers.setdefault("Cache-Control", "no-cache")
        _headers["Connection"] = "keep-alive"
        _headers["X-Accel-Buffering"] = "no"

        self.init_headers(_headers)

    @staticmethod
    async def listen_for_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                _log.debug("Got event: http.disconnect. Stop streaming.")
                break

    @staticmethod
    async def listen_for_exit_signal() -> None:
        # Check if should_exit was set before anybody started waiting
        if AppStatus.should_exit:
            return

        # Setup an Event
        if AppStatus.should_exit_event is None:
            AppStatus.should_exit_event = anyio.Event()

        # Check if should_exit got set while we set up the event
        if AppStatus.should_exit:
            return

        # Await the event
        await AppStatus.should_exit_event.wait()

    async def stream_response(self, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for data in self.body_iterator:
            chunk = ensure_bytes(data, self.sep)
            _log.debug(f"chunk: {chunk.decode()}")
            await send({"type": "http.response.body", "body": chunk, "more_body": True})

        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with anyio.create_task_group() as task_group:
            # https://trio.readthedocs.io/en/latest/reference-core.html#custom-supervisors
            async def wrap(func: Callable[[], Coroutine[None, None, None]]) -> None:
                await func()
                # noinspection PyAsyncCall
                task_group.cancel_scope.cancel()

            task_group.start_soon(wrap, partial(self.stream_response, send))
            task_group.start_soon(wrap, self.listen_for_exit_signal)

            if self.data_sender_callable:
                task_group.start_soon(self.data_sender_callable)

            await wrap(partial(self.listen_for_disconnect, receive))

        if self.background is not None:  # pragma: no cover, tested in StreamResponse
            await self.background()

    def enable_compression(self, force: bool = False) -> None:
        raise NotImplementedError
