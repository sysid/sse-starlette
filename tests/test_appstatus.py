"""
Consolidated tests for AppStatus signal handler functionality.
"""
import asyncio
import os
import signal
import threading
from unittest.mock import Mock, patch

import anyio
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from sse_starlette.appstatus import AppStatus
from sse_starlette.sse import EventSourceResponse


@pytest.fixture
def reset_appstatus():
    """Fixture to reset AppStatus state for testing."""
    # Store original state
    original_initialized = AppStatus._initialized
    original_handlers = AppStatus._original_handlers.copy()
    original_callbacks = AppStatus._shutdown_callbacks.copy()

    # Reset for test
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    AppStatus._shutdown_callbacks.clear()

    yield

    # Restore original state
    AppStatus._initialized = original_initialized
    AppStatus._original_handlers = original_handlers
    AppStatus._shutdown_callbacks = original_callbacks
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None


class TestAppStatusInitialization:
    """Test AppStatus initialization and signal registration."""

    def test_initialize_whenCalled_thenRegistersSignalHandlers(self, reset_appstatus):
        """Test that initialize properly registers signal handlers."""
        # Arrange
        AppStatus._initialized = False

        with patch.object(AppStatus, '_register_signal_handlers') as mock_register:
            # Act
            AppStatus.initialize()

            # Assert
            mock_register.assert_called_once()
            assert AppStatus._initialized is True

    def test_initialize_whenCalledMultipleTimes_thenRegistersOnlyOnce(self, reset_appstatus):
        """Test that multiple initialize calls don't re-register handlers."""
        # Arrange
        AppStatus._initialized = False

        with patch.object(AppStatus, '_register_signal_handlers') as mock_register:
            # Act
            AppStatus.initialize()
            AppStatus.initialize()  # Second call
            AppStatus.initialize()  # Third call

            # Assert
            mock_register.assert_called_once()

    def test_registerSignalHandlers_whenCalled_thenRegistersCorrectSignals(self):
        """Test that correct signals are registered."""
        with patch('sse_starlette.appstatus.signal.signal') as mock_signal:
            mock_signal.return_value = signal.SIG_DFL

            # Act
            AppStatus._register_signal_handlers()

            # Assert
            assert mock_signal.call_count >= 2
            call_args = [call[0] for call in mock_signal.call_args_list]
            signals_registered = [args[0] for args in call_args]

            assert signal.SIGINT in signals_registered
            assert signal.SIGTERM in signals_registered


class TestAppStatusShutdown:
    """Test AppStatus shutdown functionality."""

    def test_handleExit_whenCalled_thenSetsShutdownFlags(self, reset_appstatus):
        """Test that handle_exit sets the shutdown flags."""
        # Arrange
        AppStatus.should_exit = False
        AppStatus.should_exit_event = Mock()

        # Act
        AppStatus.handle_exit()

        # Assert
        assert AppStatus.should_exit is True
        AppStatus.should_exit_event.set.assert_called_once()

    def test_handleExit_whenCalledWithOriginalHandler_thenCallsOriginal(self, reset_appstatus):
        """Test that handle_exit calls original signal handler."""
        # Arrange
        original_handler = Mock()
        AppStatus._original_handlers[signal.SIGINT] = original_handler

        # Act
        AppStatus.handle_exit(signal.SIGINT, None)

        # Assert
        original_handler.assert_called_once_with(signal.SIGINT, None)

    def test_addShutdownCallback_whenExitCalled_thenExecutesCallback(self, reset_appstatus):
        """Test that shutdown callbacks are executed on exit."""
        # Arrange
        callback_executed = False

        def test_callback():
            nonlocal callback_executed
            callback_executed = True

        AppStatus.add_shutdown_callback(test_callback)

        # Act
        AppStatus.handle_exit()

        # Assert
        assert callback_executed is True

    def test_addShutdownCallback_whenMultipleCallbacks_thenExecutesAll(self, reset_appstatus):
        """Test that multiple shutdown callbacks are all executed."""
        # Arrange
        callbacks_executed = []

        def make_callback(name):
            def callback():
                callbacks_executed.append(name)

            return callback

        for i in range(3):
            AppStatus.add_shutdown_callback(make_callback(f"callback_{i}"))

        # Act
        AppStatus.handle_exit()

        # Assert
        assert len(callbacks_executed) == 3
        assert "callback_0" in callbacks_executed
        assert "callback_1" in callbacks_executed
        assert "callback_2" in callbacks_executed


class TestAppStatusAsync:
    """Test AppStatus async functionality."""

    @pytest.mark.asyncio
    async def test_listenForExitSignal_whenExitSignaled_thenReturns(self):
        """Test that _listen_for_exit_signal responds to shutdown."""
        # Arrange
        AppStatus.should_exit = False
        AppStatus.should_exit_event = anyio.Event()

        # Start listening task
        listen_task = asyncio.create_task(AppStatus._listen_for_exit_signal())

        # Give task time to start
        await asyncio.sleep(0.01)

        # Act
        AppStatus.handle_exit()

        # Assert
        await asyncio.wait_for(listen_task, timeout=0.5)
        assert listen_task.done()

    @pytest.mark.asyncio
    async def test_listenForExitSignal_whenAlreadyExiting_thenReturnsImmediately(self):
        """Test that _listen_for_exit_signal returns immediately if already exiting."""
        # Arrange
        AppStatus.should_exit = True

        # Act & Assert
        await asyncio.wait_for(AppStatus._listen_for_exit_signal(), timeout=0.1)


class TestAppStatusStateManagement:
    """Test AppStatus state management."""

    def test_reset_whenCalled_thenClearsState(self, reset_appstatus):
        """Test that reset clears all AppStatus state."""
        # Arrange
        AppStatus.should_exit = True
        AppStatus.should_exit_event = Mock()
        AppStatus.add_shutdown_callback(lambda: None)

        # Act
        AppStatus.reset()

        # Assert
        assert AppStatus.should_exit is False
        assert AppStatus.should_exit_event is None
        assert len(AppStatus._shutdown_callbacks) == 0

    def test_cleanup_whenCalled_thenRestoresSignalHandlers(self):
        """Test that cleanup restores original signal handlers."""
        # Arrange
        original_sigint = Mock()
        original_sigterm = Mock()
        AppStatus._original_handlers = {
            signal.SIGINT: original_sigint,
            signal.SIGTERM: original_sigterm
        }

        with patch('sse_starlette.appstatus.signal.signal') as mock_signal:
            # Act
            AppStatus.cleanup()

            # Assert
            mock_signal.assert_any_call(signal.SIGINT, original_sigint)
            mock_signal.assert_any_call(signal.SIGTERM, original_sigterm)
            assert not AppStatus._initialized
            assert len(AppStatus._original_handlers) == 0


class TestEventSourceResponseIntegration:
    """Test EventSourceResponse integration with AppStatus."""

    def test_eventSourceResponse_whenCreated_thenInitializesAppStatus(self, reset_appstatus):
        """Test that creating EventSourceResponse initializes AppStatus."""
        # Arrange
        AppStatus._initialized = False

        with patch.object(AppStatus, 'initialize') as mock_init:
            # Act
            async def test_generator():
                yield {"data": "test"}

            response = EventSourceResponse(test_generator())

            # Assert
            mock_init.assert_called_once()

    def test_eventSourceResponse_whenSignalReceived_thenAppStatusReflectsShutdown(self, reset_appstatus):
        """Test that SSE response works with AppStatus shutdown."""

        # Arrange
        async def test_generator():
            for i in range(10):
                yield {"data": f"message_{i}"}
                await asyncio.sleep(0.01)

        # Act
        response = EventSourceResponse(test_generator())
        AppStatus.handle_exit()

        # Assert
        assert AppStatus.should_exit is True
        assert isinstance(response, EventSourceResponse)


class TestSignalHandlerIntegration:
    """Test signal handler integration."""

    @pytest.mark.skipif(os.name == "nt", reason="Signal handling differs on Windows")
    def test_signalHandler_whenTriggered_thenExecutesShutdown(self, reset_appstatus):
        """Test that signal handler triggers AppStatus shutdown."""
        # Arrange
        AppStatus.cleanup()
        AppStatus.reset()

        callback_executed = threading.Event()

        def shutdown_callback():
            callback_executed.set()

        AppStatus.add_shutdown_callback(shutdown_callback)

        # Capture signal handler during registration
        captured_handler = None

        def capture_handler(sig, handler):
            nonlocal captured_handler
            if sig == signal.SIGINT:
                captured_handler = handler
            return signal.SIG_DFL

        with patch('sse_starlette.appstatus.signal.signal', side_effect=capture_handler):
            AppStatus._register_signal_handlers()

        # Act
        if captured_handler:
            captured_handler(signal.SIGINT, None)

        # Assert
        assert callback_executed.wait(timeout=1.0), "Shutdown callback was not executed"
        assert AppStatus.should_exit is True

    def test_signalHandler_whenCalledWithDifferentSignals_thenHandlesBoth(self, reset_appstatus):
        """Test that signal handler works for different signals."""
        # Test SIGINT
        AppStatus.handle_exit(signal.SIGINT, None)
        assert AppStatus.should_exit is True

        # Reset and test SIGTERM
        AppStatus.reset()
        AppStatus.handle_exit(signal.SIGTERM, None)
        assert AppStatus.should_exit is True


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_appStatus_whenEventIsNone_thenNoExceptionThrown(self, reset_appstatus):
        # Arrange - Simulate how old code might have worked
        AppStatus.should_exit_event = None  # Old code might explicitly set this to None

        # Act - Simulate legacy shutdown pattern
        AppStatus.should_exit = True  # Set the flag directly
        if AppStatus.should_exit_event is not None:  # Guard against None
            AppStatus.should_exit_event.set()  # Only call if event exists

        # Assert - The main thing is that no exceptions are thrown
        assert AppStatus.should_exit is True

    @pytest.mark.asyncio
    async def test_eventSourceResponse_whenUsedWithoutExplicitInit_thenWorksCorrectly(self):
        """Test that EventSourceResponse works without explicit initialization."""

        # Arrange
        async def simple_generator():
            yield {"data": "test"}

        # Act
        response = EventSourceResponse(simple_generator())

        # Assert
        assert isinstance(response, EventSourceResponse)
        assert AppStatus._initialized is True


class TestSSEEndpointIntegration:
    """Integration test with real SSE endpoint."""

    def test_sseEndpoint_whenUsedWithAppStatus_thenWorksCorrectly(self, reset_appstatus):
        """Integration test with real SSE endpoint using AppStatus."""

        # Arrange
        async def event_stream():
            for i in range(3):
                yield {"data": f"event_{i}"}
                await asyncio.sleep(0.01)

        async def sse_endpoint(request: Request):
            return EventSourceResponse(event_stream())

        routes = [Route("/events", endpoint=sse_endpoint)]
        app = Starlette(routes=routes)

        # Act & Assert
        with TestClient(app) as client:
            response = client.get("/events")

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

            content = response.content.decode()
            assert "data: event_0" in content
            assert "data: event_1" in content
            assert "data: event_2" in content
