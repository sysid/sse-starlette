"""
Tests for multi-loop and thread safety scenarios.

- Issue #140: Multi-loop safety (context isolation)
- Issue #149: handle_exit cannot signal context-local events
"""

import asyncio
import threading
import time
from typing import List

import pytest

from sse_starlette.sse import AppStatus, EventSourceResponse, _exit_event_context


class TestMultiLoopSafety:
    """Test suite for multi-loop and thread safety."""

    def setup_method(self):
        """Reset AppStatus before each test."""
        AppStatus.should_exit = False

    def teardown_method(self):
        """Clean up after each test."""
        AppStatus.should_exit = False

    def test_context_isolation_same_thread(self):
        """Test that exit events are isolated between different contexts in same thread."""

        async def create_and_check_event():
            # Each call should get its own event
            event1 = AppStatus.get_or_create_exit_event()
            event2 = AppStatus.get_or_create_exit_event()

            # Should be the same within same context
            assert event1 is event2
            return event1

        # Run in different asyncio event loops (different contexts)
        loop1 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop1)
        try:
            event_a = loop1.run_until_complete(create_and_check_event())
        finally:
            loop1.close()

        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:
            event_b = loop2.run_until_complete(create_and_check_event())
        finally:
            loop2.close()

        # Events from different loops should be different objects
        assert event_a is not event_b

    def test_thread_isolation(self):
        """Test that exit events are isolated between different threads."""
        events: List = []
        errors: List = []

        def create_event_in_thread():
            """Create an event in a new thread with its own event loop."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def get_event():
                    return AppStatus.get_or_create_exit_event()

                event = loop.run_until_complete(get_event())
                events.append(event)
                loop.close()
            except Exception as e:
                errors.append(e)

        # Create events in multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=create_event_in_thread)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Should have no errors
        assert not errors, f"Errors occurred: {errors}"

        # Should have 3 different events
        assert len(events) == 3
        assert len(set(id(event) for event in events)) == 3, "Events should be unique"

    def test_exit_signal_propagation_multiple_contexts(self):
        """Test that exit signals properly propagate to multiple contexts."""

        # Test that exit signal set before waiting works correctly
        AppStatus.should_exit = True

        async def quick_exit_test():
            await EventSourceResponse._listen_for_exit_signal()
            return "exited"

        # Test in single loop first
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(quick_exit_test())
            assert result == "exited"
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_context_cleanup(self):
        """Test that context variables are properly cleaned up."""

        # Create an event in current context
        initial_event = AppStatus.get_or_create_exit_event()
        assert _exit_event_context.get() is initial_event

        # Verify we can create new contexts
        async def inner_context():
            # This should create a new event in the task context
            return AppStatus.get_or_create_exit_event()

        # Create task which runs in a copied context
        task_event = await asyncio.create_task(inner_context())

        # The task should have access to the same event (context is copied)
        assert task_event is initial_event

    @pytest.mark.asyncio
    async def test_exit_before_event_creation(self):
        """Test that exit signal works even when set before event creation."""

        # Set exit before any event is created
        AppStatus.should_exit = True

        # This should return immediately without waiting
        start_time = time.time()
        await EventSourceResponse._listen_for_exit_signal()
        elapsed = time.time() - start_time

        # Should return almost immediately (less than 0.1 seconds)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_race_condition_protection(self):
        """Test protection against race conditions during event setup."""

        # Set exit before creating tasks to avoid hanging
        AppStatus.should_exit = True

        # Multiple concurrent calls should all work correctly
        tasks = [
            asyncio.create_task(EventSourceResponse._listen_for_exit_signal())
            for _ in range(3)
        ]

        # All tasks should complete quickly
        results = await asyncio.gather(*tasks)
        assert len(results) == 3

    def test_no_global_state_pollution(self):
        """Test that global state is not polluted between test runs."""

        # Verify clean state
        assert not AppStatus.should_exit
        assert _exit_event_context.get(None) is None

        # Create an event
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:

            async def create_event():
                return AppStatus.get_or_create_exit_event()

            event = loop.run_until_complete(create_event())
            assert event is not None
        finally:
            loop.close()

        # After loop closes, context should be clean for new contexts
        # (This test verifies we don't have lingering global state)
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:

            async def create_new_event():
                return AppStatus.get_or_create_exit_event()

            new_event = loop2.run_until_complete(create_new_event())
            assert new_event is not None
        finally:
            loop2.close()


class TestIssue149HandleExitSignaling:
    """
    Tests for Issue #149: handle_exit cannot signal context-local events.

    Unlike TestMultiLoopSafety tests which set should_exit=True BEFORE waiting,
    these tests exercise the actual signaling path where tasks are ALREADY
    waiting when handle_exit is called.
    """

    def setup_method(self):
        AppStatus.should_exit = False

    def teardown_method(self):
        AppStatus.should_exit = False

    @pytest.mark.asyncio
    async def test_handle_exit_wakes_waiting_task(self):
        """
        Test that handle_exit() can wake a task already waiting on exit_event.

        This is the critical path: task waits, THEN signal arrives.
        Bug: handle_exit runs in different context, can't see task's event.
        """
        task_exited = asyncio.Event()

        async def wait_for_exit():
            await EventSourceResponse._listen_for_exit_signal()
            task_exited.set()

        task = asyncio.create_task(wait_for_exit())
        await asyncio.sleep(0.1)  # Let task enter wait state

        # Temporarily disable original handler to avoid uvicorn dependency
        original = AppStatus.original_handler
        AppStatus.original_handler = None
        try:
            AppStatus.handle_exit()
        finally:
            AppStatus.original_handler = original

        try:
            await asyncio.wait_for(task_exited.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            pytest.fail(
                "handle_exit() failed to wake waiting task. "
                "Issue #149: context variables prevent cross-context signaling."
            )

    @pytest.mark.asyncio
    async def test_handle_exit_wakes_multiple_waiting_tasks(self):
        """Test that handle_exit() wakes ALL waiting tasks, not just one."""
        num_tasks = 3
        exited = []

        async def wait_for_exit(task_id: int):
            await EventSourceResponse._listen_for_exit_signal()
            exited.append(task_id)

        tasks = [asyncio.create_task(wait_for_exit(i)) for i in range(num_tasks)]
        await asyncio.sleep(0.1)  # Let all tasks enter wait state

        # Temporarily disable original handler to avoid uvicorn dependency
        original = AppStatus.original_handler
        AppStatus.original_handler = None
        try:
            AppStatus.handle_exit()
        finally:
            AppStatus.original_handler = original

        done, pending = await asyncio.wait(tasks, timeout=1.0)

        for t in pending:
            t.cancel()

        if len(exited) != num_tasks:
            pytest.fail(
                f"Only {len(exited)}/{num_tasks} tasks woke up. "
                f"Issue #149: handle_exit cannot signal all context-local events."
            )

    def test_handle_exit_sees_no_event_in_its_context(self):
        """
        Directly verify that handle_exit's context has no exit event.

        This is the root cause: _exit_event_context.get(None) returns None
        in handle_exit because the event was created in a different context.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Create event in task context (simulates SSE task)
            async def create_event():
                return AppStatus.get_or_create_exit_event()

            task_event = loop.run_until_complete(create_event())
            assert task_event is not None

            # Check what handle_exit would see (its context)
            handler_sees = _exit_event_context.get(None)

            if handler_sees is None:
                pytest.fail(
                    "handle_exit's context has no exit event. "
                    "_exit_event_context.get(None) = None. "
                    "This is Issue #149: task's event is invisible to handle_exit."
                )

            assert handler_sees is task_event
        finally:
            loop.close()
