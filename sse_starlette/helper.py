import asyncio


class WouldBlock(Exception):
    """Raised when a non-blocking operation would block."""
    pass


class AsyncLock:
    """A Lock wrapper that supports nowait operations."""

    def __init__(self):
        self._lock = asyncio.Lock()

    def acquire_nowait(self):
        """Attempt to acquire the lock without waiting.

        Raises:
            WouldBlock: if the lock cannot be acquired immediately
        """
        if self._lock.locked():
            raise WouldBlock()

        # Create a future that's immediately done
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        self._lock._locked = True
        return fut

    async def __aenter__(self):
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()

    async def acquire(self):
        await self._lock.acquire()

    def release(self):
        self._lock.release()
