import io
import logging
import re
import asyncio

from datetime import datetime
from typing import (
    Any,
    AsyncIterable,
    Callable,
    Coroutine,
    Iterator,
    Mapping,
    Union,    
)

from starlette.background import BackgroundTask,BackgroundTasks
from starlette.concurrency import iterate_in_threadpool,run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from starlette._utils import is_async_callable

logger = logging.getLogger(__name__)
#logger.disabled = True

# most times, we may need other logs but not ping log every 10-15s
DEBUG_PING = False

# https://stackoverflow.com/questions/58133694/graceful-shutdown-of-uvicorn-starlette-app-with-websockets
class AppStatus:
    """helper for monkey-patching the signal-handler of uvicorn"""

    should_exit = False
    should_exit_event: Union[asyncio.Event, None] = None

    @staticmethod
    def handle_exit(*args, **kwargs):
        # set bool flag before checking the event to avoid race condition
        AppStatus.should_exit = True
        # Check if event has been initialized, if so notify listeners
        if AppStatus.should_exit_event is not None:
            AppStatus.should_exit_event.set()
        original_handler(*args, **kwargs)


try:
    from uvicorn.main import Server

    original_handler = Server.handle_exit
    Server.handle_exit = AppStatus.handle_exit  # type: ignore

    def unpatch_uvicorn_signal_handler():
        """restores original signal-handler and rolls back monkey-patching.
        Normally this should not be necessary.
        """
        Server.handle_exit = original_handler

except ModuleNotFoundError:
    logger.warning("Uvicorn not used.")


class ServerSentEvent:
    def __init__(
        self,
        data: Any = None,
        *,
        event: str = None,
        id: int | str = None,
        retry: int = None,
        comment: str = None,
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
        :param int retry: Instruct the client to try reconnecting after *at least* the
            given number of milliseconds has passed in case of connection loss. Setting
            to 0 does not prevent reconnect attempts, a clean disconnect must be
            implemented on top of the SSE protocol if required (eg. as a special event
            type). The spec requires client to not attempt reconnecting if it receives a
            HTTP 204 No Content response. If a non-integer value is specified, the field
            is ignored.
        :param str comment: A colon as the first character of a line is essence
            a comment, and is ignored. Usually used as a ping message to keep connecting.
            If set, this will be a comment message.
        """
        self.data = data
        self.event = event
        self.id = id
        self.retry = retry
        self.comment = comment
        self.DEFAULT_SEPARATOR = "\r\n"
        self.LINE_SEP_EXPR = re.compile(r"\r\n|\r|\n")
        self._sep = sep if sep is not None else self.DEFAULT_SEPARATOR

    def encode(self) -> bytes:
        buffer = io.StringIO()
        if self.comment is not None:
            for chunk in self.LINE_SEP_EXPR.split(str(self.comment)):
                buffer.write(f": {chunk}")
                buffer.write(self._sep)

        if self.id is not None:
            buffer.write(self.LINE_SEP_EXPR.sub("", f"id: {self.id}"))
            buffer.write(self._sep)

        if self.event is not None:
            buffer.write(self.LINE_SEP_EXPR.sub("", f"event: {self.event}"))
            buffer.write(self._sep)

        if self.data is not None:
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


def ensure_bytes(data: Union[bytes, dict, ServerSentEvent, Any], sep: str) -> bytes:
    if isinstance(data, bytes):
        return data
    elif isinstance(data, ServerSentEvent):
        return data.encode()
    elif isinstance(data, dict):
        data["sep"] = sep
        return ServerSentEvent(**data).encode()
    else:
        return ServerSentEvent(str(data), sep=sep).encode()


Content = Union[str, bytes, dict, ServerSentEvent, Any]
# https://github.com/sysid/sse-starlette/issues/101#issue-2340755790
SyncContentStream = Iterator[Content]
AsyncContentStream = AsyncIterable[Content]
ContentStream = Union[AsyncContentStream, SyncContentStream]


class EventSourceResponse(Response):
    """Implements the ServerSentEvent Protocol:
    https://html.spec.whatwg.org/multipage/server-sent-events.html

    Responses must not be compressed by middleware in order to work.
    implementation based on Starlette StreamingResponse
    """

    body_iterator: AsyncContentStream

    DEFAULT_PING_INTERVAL = 15

    # noinspection PyMissingConstructor
    def __init__(
        self,
        content: ContentStream,
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        media_type: str = "text/event-stream",
        on_close: Callable[[], Any | Coroutine[None, None, None]]= None,
        ping: int | float = None,
        sep: str = None,
        ping_message_factory: Callable[[], ServerSentEvent] = None,
        on_open: Callable[[], Coroutine[None, None, None]]= None,
        send_timeout: float = None,        
    ) -> None:        
        if sep is not None and sep not in ["\r\n", "\r", "\n"]:
            raise ValueError(f"sep must be one of: \\r\\n, \\r, \\n, got: {sep}")
        self.DEFAULT_SEPARATOR = "\r\n"
        self.sep = sep if sep is not None else self.DEFAULT_SEPARATOR

        self.ping_message_factory = ping_message_factory

        if isinstance(content, AsyncIterable):
            self.body_iterator = content
        else:
            self.body_iterator = iterate_in_threadpool(content)
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = None # since never called super().__init__(e.t.:Response.__init__), this field(background) must be built manualy, FastApi use this field to run BackgroundTasks.
        self.on_close = on_close        
        self.on_open = on_open
        self.send_timeout = send_timeout                
        
        _headers = MutableHeaders()
        if headers is not None:  # pragma: no cover
            _headers.update(headers)

        # "The no-store response directive indicates that any caches of any kind (private or shared)
        # should not store this response."
        # -- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control

        # allow cache control header to be set by user to support fan out proxies
        # https://www.fastly.com/blog/server-sent-events-fastly
        _headers.setdefault("Cache-Control", "no-store")
        _headers["Connection"] = "keep-alive"
        _headers["X-Accel-Buffering"] = "no"

        self.init_headers(_headers)

        self.ping_interval = ping or self.DEFAULT_PING_INTERVAL
        self.active = True

        self._ping_task = None

        # https://github.com/sysid/sse-starlette/pull/55#issuecomment-1732374113
        self._send_lock = asyncio.Lock()

    @staticmethod
    async def listen_for_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                logger.debug("Got event: http.disconnect. Stop streaming.")
                break

    @staticmethod
    async def listen_for_exit_signal() -> None:
        # Check if should_exit was set before anybody started waiting
        if AppStatus.should_exit:
            return

        # Setup an Event
        if AppStatus.should_exit_event is None:
            AppStatus.should_exit_event = asyncio.Event()

        # Check if should_exit got set while we set up the event
        if AppStatus.should_exit:
            return

        # Await the event
        await AppStatus.should_exit_event.wait()

    async def stream_response(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for data in self.body_iterator:            
            chunk = ensure_bytes(data, self.sep)
            logger.debug(f"stream asend: {chunk.decode()}")
            try:
                async with asyncio.timeout(self.send_timeout) as timeout:
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            except asyncio.TimeoutError:
                if hasattr(self.body_iterator, "aclose"):
                    await self.body_iterator.aclose()

        async with self._send_lock:
            self.active = False
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.stream_response(send),name="sse_stream_response")
            tg.create_task(self._ping(send),name="sse_ping")
            
            if self.on_open:
                tg.create_task(self.on_open(),name='sse_on_open_callable')
            
            tg.create_task(self.listen_for_exit_signal(),name="sse_listen_for_exit_signal")
            tg.create_task(self.listen_for_disconnect(receive),name="sse_listen_for_disconnect").add_done_callback(lambda ctx: tg._abort())
                                                
        # clear up
        """ if self.on_close:
            await self.on_close() """
        
        # the below is actually a simplified implement of BackgourndTask, ONLY difference is: args and kwargs have both been removed.
        # for in this case, we actually don't need pass params in SSE code block. 
        # I always felt that it is not a very good idea to call BackgroundTask directly, FastApi didn't import BackgroundTask, the author has a good reason.
        if self.on_close:
            if is_async_callable(self.on_close):
                await self.on_close()
            else:
                await run_in_threadpool(self.on_close)
                

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
            raise TypeError("ping interval must be int or float")
        if value <= 0:
            raise ValueError("ping interval must be greater than 0")

        self._ping_interval = value

    async def _ping(self, send: Send) -> None:
        # Legacy proxy servers are known to, in certain cases, drop HTTP connections after a short timeout.
        # To protect against such proxy servers, authors can send a custom (ping) event
        # every 15 seconds or so.
        # Alternatively one can send periodically a comment line
        # (one starting with a ':' character)
        while self.active:
            await asyncio.sleep(self._ping_interval)
            if self.ping_message_factory:
                assert isinstance(self.ping_message_factory, Callable)  # type: ignore  # https://github.com/python/mypy/issues/6864
            ping = (
                ServerSentEvent(comment = f"⛨ ping {datetime.now()}", sep=self.sep).encode()
                if self.ping_message_factory is None
                else ensure_bytes(self.ping_message_factory(), self.sep)
            )
            
            if DEBUG_PING:
                logger.debug(f"ping {ping.decode()}")
                
            async with self._send_lock:
                if self.active:
                    await send(
                        {"type": "http.response.body", "body": ping, "more_body": True}
                    )
