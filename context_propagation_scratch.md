Chatgpt: https://chatgpt.com/c/c2c61b50-394c-4a1e-b13e-e1e05ac75bd6

The issue you're encountering stems from the interaction between asynchronous context management and the nature of streaming responses in Python. Context variables in Python are tied to the logical flow of execution, but asynchronous generators (like the one used in EventSourceResponse) can disrupt this flow, causing the context variables to become inaccessible.

Here's a detailed explanation and potential solutions:

### Explanation of the Problem
When you use EventSourceResponse to stream a response, it essentially involves yielding control back to the event loop multiple times. Each time control is yielded, the logical execution context can change, and the context variables may no longer be available. This is because context variables in Python are tied to the current task, and the yielding mechanism in asynchronous generators can break this tie.


To propagate the context variables correctly through the `EventSourceResponse`, we need to ensure that the context is maintained across asynchronous boundaries. One way to achieve this is by capturing the current context and reapplying it within the streaming response.

Here's a potential solution to modify the `EventSourceResponse` class to capture and propagate the context:

### Solution Overview
1. **Capture the context at the start of the request.**
2. **Propagate the context inside the streaming generator.**

### Code Modification

Modify the `EventSourceResponse` to capture the context and then ensure that the captured context is used in the streaming response.

#### Step 1: Modify `EventSourceResponse` Initialization
Capture the context when initializing the `EventSourceResponse`.

```python
from starlette_context import context

class EventSourceResponse(Response):
    """Implements the ServerSentEvent Protocol:
    https://html.spec.whatwg.org/multipage/server-sent-events.html

    Responses must not be compressed by middleware in order to work.
    implementation based on Starlette StreamingResponse
    """

    body_iterator: AsyncContentStream
    current_context = context.data

    DEFAULT_PING_INTERVAL = 15

    # noinspection PyMissingConstructor
    def __init__(
        self,
        content: ContentStream,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: str = "text/event-stream",
        background: Optional[BackgroundTask] = None,
        ping: Optional[int] = None,
        sep: Optional[str] = None,
        ping_message_factory: Optional[Callable[[], ServerSentEvent]] = None,
        data_sender_callable: Optional[
            Callable[[], Coroutine[None, None, None]]
        ] = None,
        send_timeout: Optional[float] = None,
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
        self.background = background
        self.data_sender_callable = data_sender_callable
        self.send_timeout = send_timeout

        _headers: dict[str, str] = {}
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
```

#### Step 2: Propagate the Context in the Streaming Response
Ensure that the captured context is re-applied within the `stream_response` method.

```python
import contextvars

class EventSourceResponse(Response):
    # ... other code ...

    async def stream_response(self, send: Send) -> None:
        context_var = contextvars.ContextVar("context")
        context_var.set(self.current_context)

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for data in self.body_iterator:
            chunk = ensure_bytes(data, self.sep)
            _log.debug("chunk: %s", chunk)
            with anyio.move_on_after(self.send_timeout) as timeout:
                await send(
                    {"type": "http.response.body", "body": chunk, "more_body": True}
                )
            if timeout.cancel_called:
                if hasattr(self.body_iterator, "aclose"):
                    await self.body_iterator.aclose()
                raise SendTimeoutError()

        async with self._send_lock:
            self.active = False
            await send({"type": "http.response.body", "body": b"", "more_body": False})
```

### Summary

By capturing the context at the start of the request and reapplying it within the streaming response, you can ensure that context variables are accessible throughout the asynchronous flow of the `EventSourceResponse`. This method ensures that the context is correctly propagated, even through asynchronous boundaries.
