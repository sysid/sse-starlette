# sse_starlette/appstatus.py
import logging
import signal
import threading
from typing import Callable, Optional

import anyio

logger = logging.getLogger(__name__)


class AppStatus:
    """ Enhanced AppStatus that handles graceful shutdown for SSE streams. """

    should_exit = False
    should_exit_event: Optional[anyio.Event] = None
    _original_handlers: dict = {}
    _shutdown_callbacks: list[Callable[[], None]] = []
    _initialized = False
    _lock = threading.RLock()  # Use RLock to allow recursive locking

    @classmethod
    def initialize(cls) -> None:
        """Initialize signal handlers for graceful shutdown."""
        with cls._lock:
            if cls._initialized:
                return

            cls._initialized = True
            cls._register_signal_handlers()
            logger.debug("AppStatus initialized with signal handlers")

    @classmethod
    def _register_signal_handlers(cls) -> None:
        """Register signal handlers for SIGINT and SIGTERM."""

        def signal_handler(signum: int, frame) -> None:
            logger.debug(f"Received signal {signum}, initiating graceful shutdown")
            cls.handle_exit(signum, frame)

        for sig in [signal.SIGINT, signal.SIGTERM]:
            try:
                original = signal.signal(sig, signal_handler)
                cls._original_handlers[sig] = original
                logger.debug(f"Registered signal handler for {sig}")
            except (ValueError, OSError) as e:
                # Signal might not be available on all platforms
                logger.warning(f"Could not register handler for signal {sig}: {e}")

    @classmethod
    def handle_exit(cls, signum: Optional[int] = None, frame=None) -> None:
        """
        Handle exit signal by setting shutdown flags and notifying waiters.

        Args:
            signum: Signal number (for signal handler compatibility)
            frame: Frame object (for signal handler compatibility)
        """
        logger.debug("AppStatus.handle_exit called")
        cls.should_exit = True

        # Notify all waiting tasks
        if cls.should_exit_event is not None:
            try:
                cls.should_exit_event.set()
            except Exception as e:
                logger.error(f"Error setting exit event: {e}")
                # This is always critical - re-raise
                raise

        # Execute shutdown callbacks
        for callback in cls._shutdown_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}")

        # Call original handler if it exists
        if signum and signum in cls._original_handlers:
            original = cls._original_handlers[signum]
            if original and original != signal.SIG_DFL and original != signal.SIG_IGN:
                try:
                    original(signum, frame)
                except Exception as e:
                    # Original handler errors are usually not critical
                    logger.error(f"Error calling original signal handler: {e}")

    @classmethod
    def add_shutdown_callback(cls, callback: Callable[[], None]) -> None:
        """Add a callback to be executed on shutdown."""
        with cls._lock:
            cls._shutdown_callbacks.append(callback)

    @classmethod
    def reset(cls) -> None:
        """Reset AppStatus state (useful for testing)."""
        # Don't use lock here to avoid deadlock in cleanup
        cls.should_exit = False
        cls.should_exit_event = None
        cls._shutdown_callbacks.clear()

    @classmethod
    def cleanup(cls) -> None:
        """Clean up signal handlers and reset state."""
        handlers_to_restore = {}
        with cls._lock:
            handlers_to_restore = cls._original_handlers.copy()
            cls._original_handlers.clear()
            cls._initialized = False

        # Restore handlers outside the lock: Avoid holding locks during system calls
        for sig, original in handlers_to_restore.items():
            try:
                if original is not None:
                    signal.signal(sig, original)
            except (ValueError, OSError) as e:
                logger.warning(f"Could not restore signal handler for {sig}: {e}")

        cls.reset()

    @staticmethod
    async def _listen_for_exit_signal() -> None:
        """Watch for shutdown signals (e.g. SIGINT, SIGTERM) so we can break the event loop."""
        # Check if should_exit was set before anybody started waiting
        if AppStatus.should_exit:
            return

        if AppStatus.should_exit_event is None:
            AppStatus.should_exit_event = anyio.Event()

        # Check if should_exit got set while we set up the event
        if AppStatus.should_exit:
            return

        await AppStatus.should_exit_event.wait()


# Auto-initialization for backward compatibility
# This ensures the signal handlers are registered when the module is imported
try:
    AppStatus.initialize()
except Exception as e:
    logger.debug(f"Could not auto-initialize AppStatus: {e}")
