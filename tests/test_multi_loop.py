"""
Tests for multi-loop and thread safety scenarios.

- Issue #140: Multi-loop safety (thread isolation)
- Issue #149: handle_exit cannot signal context-local events (FIXED via watcher)
- Issue #152: Watcher task leak (FIXED by using threading.local instead of ContextVar)

Setup/teardown handled by conftest.reset_shutdown_state fixture.
"""

import asyncio
import threading
from typing import List

import pytest

from sse_starlette.sse import (
    AppStatus,
    EventSourceResponse,
    _get_shutdown_state,
)


class TestMultiLoopSafety:
    """Test suite for multi-loop and thread safety."""

    def test_same_thread_shares_state(self):
        """Test that same thread shares shutdown state (Issue #152 fix).

        With threading.local, all code in the same thread shares state,
        preventing multiple watchers from being spawned.
        """

        async def get_state():
            return _get_shutdown_state()

        # Run in different asyncio event loops (still same thread)
        loop1 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop1)
        try:
            state_a = loop1.run_until_complete(get_state())
        finally:
            loop1.close()

        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:
            state_b = loop2.run_until_complete(get_state())
        finally:
            loop2.close()

        # With threading.local, same thread = same state
        assert state_a is state_b, "Same thread should share state (Issue #152 fix)"

    def test_thread_isolation(self):
        """Test that shutdown state is isolated between different threads."""
        states: List = []
        errors: List = []

        def get_state_in_thread():
            """Get state in a new thread with its own event loop."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def get_state():
                    return _get_shutdown_state()

                state = loop.run_until_complete(get_state())
                states.append(state)
                loop.close()
            except Exception as e:
                errors.append(e)

        # Get state in multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=get_state_in_thread)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert not errors, f"Errors occurred: {errors}"
        assert len(states) == 3
        assert len(set(id(s) for s in states)) == 3, "States should be unique per thread"

class TestIssue149HandleExitSignaling:
    """
    Tests for Issue #149: handle_exit cannot signal context-local events.

    Fixed by watcher pattern: a single watcher polls should_exit and
    broadcasts to all registered events in the same thread.
    """

    @pytest.mark.asyncio
    async def test_handle_exit_wakes_waiting_task(self):
        """
        Test that handle_exit() wakes a task waiting on _listen_for_exit_signal.

        The watcher polls should_exit every 0.5s, so we need to wait for that.
        """
        task_exited = asyncio.Event()

        async def wait_for_exit():
            await EventSourceResponse._listen_for_exit_signal()
            task_exited.set()

        task = asyncio.create_task(wait_for_exit())
        await asyncio.sleep(0.1)  # Let task start waiting

        original = AppStatus.original_handler
        AppStatus.original_handler = None  # prevent calling Uvicorn handler if existent
        try:
            # Simulate shutdown signal
            AppStatus.handle_exit()
        finally:
            AppStatus.original_handler = original

        # Wait for watcher to poll and broadcast (max 0.5s + margin)
        try:
            await asyncio.wait_for(task_exited.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            pytest.fail("handle_exit() failed to wake waiting task within timeout.")

    @pytest.mark.asyncio
    async def test_handle_exit_wakes_multiple_waiting_tasks(self):
        """Test that handle_exit() wakes ALL waiting tasks."""
        num_tasks = 3
        exited = []

        async def wait_for_exit(task_id: int):
            await EventSourceResponse._listen_for_exit_signal()
            exited.append(task_id)

        tasks = [asyncio.create_task(wait_for_exit(i)) for i in range(num_tasks)]
        await asyncio.sleep(0.1)  # Let all tasks start waiting

        original = AppStatus.original_handler
        AppStatus.original_handler = None
        try:
            AppStatus.handle_exit()
        finally:
            AppStatus.original_handler = original

        # Wait for watcher to broadcast
        done, pending = await asyncio.wait(tasks, timeout=1.0)

        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        assert len(exited) == num_tasks, f"Only {len(exited)}/{num_tasks} tasks woke up."

    @pytest.mark.asyncio
    async def test_all_tasks_share_same_shutdown_state(self):
        """
        Verify that all tasks created with asyncio.create_task() in the same thread
        share the same _ShutdownState.
        """
        state_ids = []

        async def get_state_in_task(task_id: int):
            state = _get_shutdown_state()
            state_ids.append((task_id, id(state)))

        # Create multiple tasks
        tasks = [asyncio.create_task(get_state_in_task(i)) for i in range(3)]
        await asyncio.gather(*tasks)

        # Verify all tasks got the same state instance
        unique_ids = set(state_id for _, state_id in state_ids)
        assert len(unique_ids) == 1, (
            f"Expected all tasks to share one state, but found {len(unique_ids)} unique states. "
            f"This indicates threading.local is not working as expected."
        )

