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


class EventSourceResponse3(Response):
    """Implements the ServerSentEvent Protocol:
    https://www.w3.org/TR/2009/WD-eventsource-20090421/

    Responses must not be compressed by middleware in order to work.
    implementation based on Starlette StreamingResponse
    """

    DEFAULT_PING_INTERVAL = 15

    # noinspection PyMissingConstructor
    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Optional[Dict] = None,
        media_type: str = "text/event-stream",
        background: Optional[BackgroundTask] = None,
        ping: Optional[int] = None,
        sep: Optional[str] = None,
        ping_message_factory: Optional[Callable[[], ServerSentEvent]] = None,
        data_sender_callable: Optional[
            Callable[[], Coroutine[None, None, None]]
        ] = None,
    ) -> None:
        if sep is not None and sep not in ["\r\n", "\r", "\n"]:
            raise ValueError(f"sep must be one of: \\r\\n, \\r, \\n, got: {sep}")
        self.sep = sep
        self.ping_message_factory = ping_message_factory
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

        self.ping_interval = self.DEFAULT_PING_INTERVAL if ping is None else ping
        self.active = True

        self._ping_task = None

        # https://github.com/sysid/sse-starlette/pull/55#issuecomment-1732374113
        self._send_lock = anyio.Lock()

    @staticmethod
    async def listen_for_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                _log.debug("Got event: http.disconnect. Stop streaming.")
                print("xxxxxxxxxxxxxxx Disconnect ")
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

        async with self._send_lock:
            self.active = False
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with anyio.create_task_group() as task_group:
            # https://trio.readthedocs.io/en/latest/reference-core.html#custom-supervisors
            async def wrap(func: Callable[[], Coroutine[None, None, None]]) -> None:
                await func()
                # noinspection PyAsyncCall
                task_group.cancel_scope.cancel()

            task_group.start_soon(wrap, partial(self.stream_response, send))
            task_group.start_soon(wrap, partial(self._ping, send))
            task_group.start_soon(wrap, self.listen_for_exit_signal)

            if self.data_sender_callable:
                task_group.start_soon(self.data_sender_callable)

            await wrap(partial(self.listen_for_disconnect, receive))

        if self.background is not None:  # pragma: no cover, tested in StreamResponse
            await self.background()

    def enable_compression(self, force: bool = False) -> None:
        raise NotImplementedError

    @property
    def ping_interval(self) -> Union[int, float]:
        """Time interval between two ping massages"""
        return self._ping_interval

    @ping_interval.setter
    def ping_interval(self, value: Union[int, float]) -> None:
        """Setter for ping_interval property.

        :param int value: interval in sec between two ping values.
        """

        if not isinstance(value, (int, float)):
            raise TypeError("ping interval must be int")
        if value < 0:
            raise ValueError("ping interval must be greater then 0")

        self._ping_interval = value

    async def _ping(self, send: Send) -> None:
        # Legacy proxy servers are known to, in certain cases, drop HTTP connections after a short timeout.
        # To protect against such proxy servers, authors can send a custom (ping) event
        # every 15 seconds or so.
        # Alternatively one can send periodically a comment line
        # (one starting with a ':' character)
        while self.active:
            await anyio.sleep(self._ping_interval)
            if self.ping_message_factory:
                assert isinstance(self.ping_message_factory, Callable)  # type: ignore  # https://github.com/python/mypy/issues/6864
            ping = (
                ServerSentEvent(comment=f"ping - {datetime.utcnow()}").encode()
                if self.ping_message_factory is None
                else ensure_bytes(self.ping_message_factory(), self.sep)
            )
            _log.debug(f"ping: {ping.decode()}")
            async with self._send_lock:
                if self.active:
                    await send({"type": "http.response.body", "body": ping, "more_body": True})
