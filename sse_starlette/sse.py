import asyncio
import contextlib
import enum
import inspect
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional, Union

from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool, run_until_first_complete
from starlette.responses import Response
from starlette.types import Receive, Scope, Send


# https://stackoverflow.com/questions/58133694/graceful-shutdown-of-uvicorn-starlette-app-with-websockets
class AppStatus:
    """ helper for monkeypatching the signal-handler of uvicorn """

    should_exit = False

    @staticmethod
    def handle_exit(*args, **kwargs):
        AppStatus.should_exit = True
        original_handler(*args, **kwargs)


try:
    from uvicorn.config import logger as _log  # TODO: remove
    from uvicorn.main import Server

    original_handler = Server.handle_exit
    Server.handle_exit = AppStatus.handle_exit

    def unpatch_uvicorn_signal_handler():
        """restores original signal-handler and rolls back monkey-patching.
        Normally this should not be necessary.
        """
        Server.handle_exit = original_handler


except ModuleNotFoundError as e:
    _log = logging.getLogger(__name__)
    # logging.basicConfig(level=logging.INFO)
    _log.debug(f"Uvicorn not used, falling back to python standard logging.")


class SseState(enum.Enum):
    CONNECTING = 0
    OPENED = 1
    CLOSED = 2


class ServerSentEvent:
    def __init__(
        self,
        data: Any,
        *,
        event: Optional[str] = None,
        id: Optional[int] = None,
        retry: Optional[int] = None,
        sep: str = None,
    ) -> None:
        """Send data using EventSource protocol

        :param str data: The data field for the message.
        :param str id: The event ID to set the EventSource object's last
            event ID value to.
        :param str event: The event's type. If this is specified, an event will
            be dispatched on the browser to the listener for the specified
            event name; the web site would use addEventListener() to listen
            for named events. The default event type is "message".
        :param int retry: The reconnection time to use when attempting to send
            the event. [What code handles this?] This must be an integer,
            specifying the reconnection time in milliseconds. If a non-integer
            value is specified, the field is ignored.
        """
        self.data = data
        self.event = event
        self.id = id
        self.retry = retry

        self.DEFAULT_SEPARATOR = "\r\n"
        self.LINE_SEP_EXPR = re.compile(r"\r\n|\r|\n")
        self._sep = sep if sep is not None else self.DEFAULT_SEPARATOR

    def encode(self) -> bytes:
        buffer = io.StringIO()
        if self.id is not None:
            buffer.write(self.LINE_SEP_EXPR.sub("", f"id: {self.id}"))
            buffer.write(self._sep)

        if self.event is not None:
            buffer.write(self.LINE_SEP_EXPR.sub("", f"event: {self.event}"))
            buffer.write(self._sep)

        for chunk in self.LINE_SEP_EXPR.split(str(self.data)):
            buffer.write(f"data: {chunk}")
            buffer.write(self._sep)

        if self.retry is not None:
            if not isinstance(self.retry, int):
                raise TypeError("retry argument must be int")
            buffer.write(f"retry: {self.retry}")
            buffer.write(self._sep)

        buffer.write(self._sep)
        return buffer.getvalue().encode("utf-8")


class EventSourceResponse(Response):
    """Implements the ServerSentEvent Protocol: https://www.w3.org/TR/2009/WD-eventsource-20090421/

    Responses must not be compressed by middleware in order to work properly.
    """

    DEFAULT_PING_INTERVAL = 15

    # noinspection PyMissingConstructor: follow Starlette StreamingResponse
    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: dict = None,
        media_type: str = "text/html",
        background: BackgroundTask = None,
        ping: int = None,
        sep: str = None,
    ) -> None:
        # super().__init__()  # follow Starlette StreamingResponse
        self.sep = sep
        if inspect.isasyncgen(content):
            self.body_iterator = content
        else:
            self.body_iterator = iterate_in_threadpool(content)
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = background

        _headers = dict()
        if headers is not None:  # pragma: no cover
            _headers.update(headers)

        # mandatory for servers-sent events headers
        _headers["Content-Type"] = "text/event-stream"
        _headers["Cache-Control"] = "no-cache"
        _headers["Connection"] = "keep-alive"
        _headers["X-Accel-Buffering"] = "no"
        # _headers['Transfer-Encoding'] = 'chunked'

        self.init_headers(_headers)

        self._loop = None
        self.ping_interval = self.DEFAULT_PING_INTERVAL if ping is None else ping
        self._ping_task = None
        self.active = True

        self._loop = asyncio.get_event_loop()
        self._ping_task = None

    @staticmethod
    async def listen_for_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                _log.debug(f"Got event: http.disconnect. Stop streaming.")
                break

    @staticmethod
    async def listen_for_exit_signal() -> None:
        while not AppStatus.should_exit:
            await asyncio.sleep(1.0)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await run_until_first_complete(
            (self.stream_response, {"send": send}),
            (self.listen_for_disconnect, {"receive": receive}),
            (self.listen_for_exit_signal, {}),
        )
        self.stop_streaming()
        await self.wait()
        _log.debug(f"streaming stopped.")

        if self.background is not None:  # pragma: no cover, tested in StreamResponse
            await self.background()

    async def stream_response(self, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )

        self._ping_task = self._loop.create_task(self._ping(send))  # type: ignore

        async for data in self.body_iterator:
            if isinstance(data, dict):
                chunk = ServerSentEvent(**data).encode()
            else:
                chunk = ServerSentEvent(str(data), sep=self.sep).encode()
            _log.debug(f"chunk: {chunk.decode()}")
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def wait(self) -> None:
        """EventSourceResponse object is used for streaming data to the client,
        this method returns future, so we can wait until connection will
        be closed or other task explicitly call ``stop_streaming`` method.
        """
        if self._ping_task is None:
            raise RuntimeError("Response is not started")
        with contextlib.suppress(asyncio.CancelledError):
            await self._ping_task
            _log.debug(f"SSE ping stopped.")  # pragma: no cover

    def stop_streaming(self) -> None:
        """Used in conjunction with ``wait`` could be called from other task
        to notify client that server no longer wants to stream anything.
        """
        if self._ping_task is None:
            raise RuntimeError("Response is not started")
        self._ping_task.cancel()

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
            await asyncio.sleep(self._ping_interval)
            ping = ServerSentEvent(datetime.utcnow(), event="ping").encode()
            _log.debug(f"ping: {ping.decode()}")
            await send({"type": "http.response.body", "body": ping, "more_body": True})
