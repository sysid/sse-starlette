import asyncio

"""
https://github.com/sysid/sse-starlette/issues/152

python examples/issues/issue152.py
"""

async def test_leak():
    from sse_starlette.sse import _ensure_watcher_started_on_this_loop, AppStatus

    def count_watchers():
        return sum(
            1 for t in asyncio.all_tasks()
            if t.get_coro() and '_shutdown_watcher' in t.get_coro().__qualname__
        )

    print(f"Before: {count_watchers()} watchers")

    # Simulate 10 SSE connections
    async def trigger():
        _ensure_watcher_started_on_this_loop()

    await asyncio.gather(*[asyncio.create_task(trigger()) for _ in range(10)])
    await asyncio.sleep(0.5)

    print(f"After:  {count_watchers()} watchers (expected: 1)")

    # Cleanup
    AppStatus.should_exit = True
    await asyncio.sleep(1)


asyncio.run(test_leak())
