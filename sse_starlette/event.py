import io
import re
from abc import ABC, abstractmethod
from typing import Optional, Any, Union, Callable


class ServerSentEventABC(ABC):
    """
    Abstract base class to format data for Server-Sent Events (SSE).
    """

    @property
    @abstractmethod
    def _LINE_SEP_EXPR(self):
        pass

    @property
    @abstractmethod
    def DEFAULT_SEPARATOR(self):
        pass

    @property
    @abstractmethod
    def TAG_COMMENT(self):
        pass

    @property
    @abstractmethod
    def TAG_ID(self):
        pass

    @property
    @abstractmethod
    def TAG_EVENT(self):
        pass

    @property
    @abstractmethod
    def TAG_DATA(self):
        pass

    @property
    @abstractmethod
    def TAG_RETRY(self):
        pass

    @abstractmethod
    def __init__(
        self,
        data: Optional[Any] = None,
        *,
        event: Optional[Any] = None,
        id: Optional[Any] = None,
        retry: Optional[int] = None,
        comment: Optional[Any] = None,
        sep: Optional[Any] = None,
    ) -> None:
        pass

    @abstractmethod
    def _process_chunk(self, chunk):
        """Process a chunk based on the implementation type (str or bytes)"""
        pass

    @abstractmethod
    def _process_retry(self, retry: int):
        """Format the retry value based on implementation type"""
        pass

    @abstractmethod
    def _encode_impl(self, write_fn: Callable) -> None:
        """Implementation-specific encoding logic"""
        pass

    @abstractmethod
    def encode(self) -> bytes:
        """Encode to SSE format and return bytes"""
        pass


class ServerSentEvent(ServerSentEventABC):
    """
    Helper class to format string data for Server-Sent Events (SSE).
    """

    _LINE_SEP_EXPR = re.compile(r"\r\n|\r|\n")
    DEFAULT_SEPARATOR = "\r\n"

    TAG_COMMENT = ": "
    TAG_ID = "id: "
    TAG_EVENT = "event: "
    TAG_DATA = "data: "
    TAG_RETRY = "retry: "

    def __init__(
        self,
        data: Optional[Any] = None,
        *,
        event: Optional[str] = None,
        id: Optional[str] = None,
        retry: Optional[int] = None,
        comment: Optional[str] = None,
        sep: Optional[str] = None,
    ) -> None:
        self.data = str(data) if data is not None else None
        self.event = event
        self.id = id
        self.retry = retry
        self.comment = comment
        self._sep = sep if sep is not None else self.DEFAULT_SEPARATOR

    def _process_chunk(self, chunk):
        return chunk

    def _process_retry(self, retry: int):
        return str(retry)

    def _encode_impl(self, write_fn: Callable) -> None:
        if self.comment is not None:
            for chunk in self._LINE_SEP_EXPR.split(self.comment):
                write_fn(f"{self.TAG_COMMENT}{self._process_chunk(chunk)}{self._sep}")

        if self.id is not None:
            # Clean newlines in the event id
            clean_id = self._LINE_SEP_EXPR.sub("", self.id)
            write_fn(f"{self.TAG_ID}{clean_id}{self._sep}")

        if self.event is not None:
            # Clean newlines in the event name
            clean_event = self._LINE_SEP_EXPR.sub("", self.event)
            write_fn(f"{self.TAG_EVENT}{clean_event}{self._sep}")

        if self.data is not None:
            # Break multi-line data into multiple data: lines
            for chunk in self._LINE_SEP_EXPR.split(self.data):
                write_fn(f"{self.TAG_DATA}{self._process_chunk(chunk)}{self._sep}")

        if self.retry is not None:
            if not isinstance(self.retry, int):
                raise TypeError("retry argument must be int")
            write_fn(f"{self.TAG_RETRY}{self._process_retry(self.retry)}{self._sep}")

        write_fn(self._sep)

    def encode(self) -> bytes:
        buffer = io.StringIO()
        self._encode_impl(buffer.write)
        return buffer.getvalue().encode("utf-8")


class ServerSentEventBytes(ServerSentEventABC):
    """
    Helper class to format bytes data for Server-Sent Events (SSE).
    """

    _LINE_SEP_EXPR = re.compile(br"\r\n|\r|\n")
    DEFAULT_SEPARATOR = b"\r\n"

    TAG_COMMENT = b": "
    TAG_ID = b"id: "
    TAG_EVENT = b"event: "
    TAG_DATA = b"data: "
    TAG_RETRY = b"retry: "

    def __init__(
        self,
        data: Optional[bytes] = None,
        *,
        event: Optional[bytes] = None,
        id: Optional[bytes] = None,
        retry: Optional[int] = None,
        comment: Optional[bytes] = None,
        sep: Optional[bytes] = None,
    ) -> None:
        self.data = data
        self.event = event
        self.id = id
        self.retry = retry
        self.comment = comment
        self._sep = sep if sep is not None else self.DEFAULT_SEPARATOR

    def _process_chunk(self, chunk):
        return chunk

    def _process_retry(self, retry: int):
        return str(retry).encode("utf-8")

    def _encode_impl(self, write_fn: Callable) -> None:
        if self.comment is not None:
            for chunk in self._LINE_SEP_EXPR.split(self.comment):
                write_fn(self.TAG_COMMENT)
                write_fn(self._process_chunk(chunk))
                write_fn(self._sep)

        if self.id is not None:
            # Clean newlines in the event id
            write_fn(self.TAG_ID)
            write_fn(self._LINE_SEP_EXPR.sub(b"", self.id))
            write_fn(self._sep)

        if self.event is not None:
            # Clean newlines in the event name
            write_fn(self.TAG_EVENT)
            write_fn(self._LINE_SEP_EXPR.sub(b"", self.event))
            write_fn(self._sep)

        if self.data is not None:
            # Break multi-line data into multiple data: lines
            for chunk in self._LINE_SEP_EXPR.split(self.data):
                write_fn(self.TAG_DATA)
                write_fn(self._process_chunk(chunk))
                write_fn(self._sep)

        if self.retry is not None:
            if not isinstance(self.retry, int):
                raise TypeError("retry argument must be int")
            write_fn(self.TAG_RETRY)
            write_fn(self._process_retry(self.retry))
            write_fn(self._sep)

        write_fn(self._sep)

    def encode(self) -> bytes:
        buffer = io.BytesIO()
        self._encode_impl(buffer.write)
        return buffer.getvalue()


def ensure_bytes(data: Union[bytes, dict, ServerSentEventABC, Any], sep: str) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, ServerSentEventABC):
        return data.encode()
    if isinstance(data, dict):
        data["sep"] = sep
        return ServerSentEvent(**data).encode()
    return ServerSentEvent(data, sep=sep).encode()
