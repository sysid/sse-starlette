# SSE-Starlette Constitution

## Authority Chain

1. `~/.claude/CLAUDE.md` — global engineering principles (supreme authority)
2. `~/dev/s/instructions/development-standards.md` § 3 (Python Project Type) — project structure, tooling, CI/CD conventions
3. `sse-starlette/CLAUDE.md` — project-specific architecture documentation
4. This constitution — sse-starlette-specific design rules not covered above

Conflicts: higher-numbered documents yield to lower-numbered ones.

## Core Principles

### I. Simplicity & YAGNI
Per `CLAUDE.md` § Code Standards / Simplicity. No additions.

### II. Test-First (NON-NEGOTIABLE)
Per `CLAUDE.md` § Testing. Project-specific additions:

- **Unit tests**: `make test-unit` (excludes integration/experimentation markers)
- **Integration tests**: Docker-based, marked `@pytest.mark.integration`, run via `make test-docker`
- **Issue regression tests**: File per issue in `tests/test_issue{N}.py`
- **Test naming**: `test_{method}_when{Condition}_then{Expected}`
- **Async testing**: `pytest-asyncio` with `asyncio_mode = "auto"`, function-scoped loop
- **Fixture**: `reset_shutdown_state` autouse fixture resets `AppStatus` and `_thread_state` per test
- **ExceptionGroup handling**: Use `collapse_excgroups()` from `tests/anyio_compat`

### III. Async Correctness
SSE streaming demands rigorous async discipline:

- **Task coordination**: Use `anyio.create_task_group()` — never raw `asyncio.create_task()`
- **Cancellation safety**: Cleanup code that must `await` during cancellation MUST use `anyio.CancelScope(shield=True)`
- **Send serialization**: All send operations go through `anyio.Lock()` — no concurrent writes to the same connection
- **Thread isolation**: Per-thread state via `threading.local()`, never `contextvars.ContextVar` for cross-loop state
- **One watcher per thread**: N connections in the same thread share 1 shutdown watcher — no watcher proliferation
- **anyio over asyncio**: Use `anyio` primitives (Event, Lock, sleep, create_task_group) for backend portability

### IV. Connection Lifecycle
Every SSE connection follows this contract:

```
open → stream (data + ping) → close (graceful or forced)
         ↑                        ↑
    disconnect detection    shutdown signal
```

- **Streaming**: Generator yields `ServerSentEvent` dicts; `_stream_response` handles serialization and send
- **Ping**: Periodic keep-alive via comment lines (configurable interval)
- **Disconnect detection**: Poll `request.is_disconnected()` — do not rely on send failures alone
- **Shutdown**: `AppStatus.should_exit` → per-thread event broadcast → task group cancellation
- **Closing frame**: `more_body=False` MUST be sent in `finally` block (shielded) to support middleware chains (Issue #164)

### V. Backwards Compatibility
Per `CLAUDE.md`: no backward compatibility without Tom's explicit approval.

Additional sse-starlette rule: **new parameters MUST have defaults that preserve existing behavior**. Users who don't pass `shutdown_event` or `shutdown_grace_period` get identical behavior to the previous version.

## Technology Stack

Per `development-standards.md` § 3 (Python Project Type), with these specifics:

| Concern           | Choice                          |
|-------------------|---------------------------------|
| Async runtime     | `anyio >= 4.7.0`               |
| Framework         | Starlette (ASGI)                |
| ASGI servers      | uvicorn, granian, daphne        |
| Formatter/Linter  | ruff                            |
| Type checker      | ty                              |
| Test runner       | pytest + pytest-asyncio         |
| Build/Version     | uv + bump-my-version            |

## Governance

- This constitution is subordinate to `CLAUDE.md` and `development-standards.md`
- Amendments require Tom's approval
- All changes must pass: `make lint`, `make ty`, `make test-unit`

**Version**: 1.0.0 | **Ratified**: 2026-02-28
