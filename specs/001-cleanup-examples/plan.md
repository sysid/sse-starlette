# Implementation Plan: Cleanup and Consolidate Examples

**Branch**: `001-cleanup-examples` | **Date**: 2026-02-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-cleanup-examples/spec.md`

## Summary

Consolidate 20+ example files across 4 directories into 7 focused, working examples in a flat structure. Remove redundant files, promote two examples from subdirectories, create one new example (cooperative shutdown), merge one unique pattern, and add a professional README.

## Technical Context

**Language/Version**: Python >=3.10
**Primary Dependencies**: sse-starlette (this project), anyio >=4.7.0, starlette
**Storage**: N/A
**Testing**: Manual verification — each example must start and serve SSE events via `curl -N`
**Target Platform**: Any (examples are educational, not deployed)
**Project Type**: Library (examples subdirectory)
**Performance Goals**: N/A
**Constraints**: Examples must use only public APIs; optional deps (FastAPI, SQLAlchemy) documented in README
**Scale/Scope**: 7 example files + 1 README

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Simplicity & YAGNI | **PASS** | Removing 18 files, adding 1. Net reduction of complexity. |
| II. Test-First | **N/A** | Examples are not library code. Verification is manual (`python <file>.py` + `curl -N`). |
| III. Async Correctness | **PASS** | Kept examples use `anyio` primitives. New 07_cooperative_shutdown will use `anyio.Event`. |
| IV. Connection Lifecycle | **PASS** | Examples demonstrate the standard lifecycle. |
| V. Backwards Compatibility | **N/A** | Examples are not API surface. |
| Governance (lint/ty/test) | **PASS** | `make lint`, `make ty`, `make test-unit` must still pass after changes. |

No violations. Complexity tracking table not needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-cleanup-examples/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── spec.md              # Feature specification
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
examples/
├── README.md
├── 01_basic_sse.py
├── 02_broadcasting.py
├── 03_database_streaming.py
├── 04_advanced_features.py
├── 05_memory_channels.py
├── 06_send_timeout.py
└── 07_cooperative_shutdown.py
```

**Structure Decision**: Flat directory. All subdirectories (`demonstrations/`, `issues/`) and their contents removed. Each example is self-contained with docstring, `if __name__` block, and curl test instructions.

## Phase 0: Research

### Research Items

| # | Question | Resolution |
|---|----------|------------|
| R1 | Do kept examples (01-04) run without modification? | Yes. All imports are public APIs. Dependencies: 01/02/04 need FastAPI+uvicorn (dev deps); 03 additionally needs SQLAlchemy+aiosqlite (optional dep group `examples`). No bugs found. |
| R2 | Do promoted examples (memory_channels, frozen_client) need changes? | Minor: file rename, update docstring format for consistency, add `if __name__` startup messages matching kept examples' style. `memory_channels.py` runs with core deps only. `frozen_client.py` needs uvicorn. |
| R3 | What does the cooperative shutdown example look like? | Pattern documented in CLAUDE.md: generator takes `anyio.Event`, yields events in a loop checking `shutdown_event.is_set()`, yields a farewell event on shutdown. `EventSourceResponse` takes `shutdown_event` and `shutdown_grace_period` params. |
| R4 | What happens to `02_message_broadcasting.py` rename to `02_broadcasting.py`? | Rename file. The content stays the same — the `_message_` part is redundant in the filename since the docstring explains it fully. |
| R5 | What merges from `main_endless_conditional.py` into `01_basic_sse.py`? | The conditional yield pattern: a generator that only yields when it has data, sleeping between checks. Add as a third endpoint showing the "conditional data availability" pattern. Keep it minimal. |

### Research Detail: Cooperative Shutdown Example (R3)

From the CLAUDE.md documented pattern and the library's `sse.py` source:

```python
# Key API surface for 07_cooperative_shutdown.py:
EventSourceResponse(
    generator(),
    shutdown_event=anyio.Event(),       # Library sets this when shutdown detected
    shutdown_grace_period=5.0,          # Seconds to wait before force-cancel
)
```

The generator pattern:
1. Accept `shutdown_event` from the endpoint function
2. Loop: yield data events, periodically check `shutdown_event.is_set()`
3. On shutdown: yield a farewell event, then return naturally
4. `EventSourceResponse` handles the grace period and force-cancellation

No external dependencies needed — uses only `anyio` (core dep) and `sse_starlette`.

## Phase 1: Design

### File Operations Plan

The operations below are ordered to avoid data loss:

**Step 1: Promote files (copy from subdirectories before deletion)**
- `demonstrations/advanced_patterns/memory_channels.py` → `examples/05_memory_channels.py`
- `demonstrations/production_scenarios/frozen_client.py` → `examples/06_send_timeout.py`

**Step 2: Create new file**
- Write `examples/07_cooperative_shutdown.py`

**Step 3: Modify kept files**
- `01_basic_sse.py`: Add conditional yield endpoint (from `main_endless_conditional.py`)
- `02_message_broadcasting.py`: Rename to `02_broadcasting.py`
- `03_database_streaming.py`: No changes needed (already clean)
- `04_advanced_features.py`: No changes needed (already clean)

**Step 4: Remove files**
- `example.py`, `stream_generator.py`, `stream_generator_multiple.py`
- `demo_client.html`, `example.db`
- Entire `demonstrations/` directory
- Entire `issues/` directory

**Step 5: Write README**
- `examples/README.md`

**Step 6: Verify**
- Each example runs and serves SSE events
- `make lint` passes
- `make test-unit` passes (existing tests unaffected)

### README Structure

```markdown
# Examples

Runnable examples demonstrating sse-starlette features.

## Prerequisites

- `pip install sse-starlette` (or install from source)
- Most examples need: `pip install fastapi uvicorn`
- Example 03 additionally needs: `pip install sqlalchemy[asyncio] aiosqlite`

## Examples

| Example | Feature | Dependencies |
|---------|---------|-------------|
| [01_basic_sse.py](01_basic_sse.py) | Basic streaming (Starlette + FastAPI) | fastapi, uvicorn |
| [02_broadcasting.py](02_broadcasting.py) | Multi-client broadcasting | fastapi, uvicorn |
| [03_database_streaming.py](03_database_streaming.py) | Thread-safe DB sessions in SSE | fastapi, uvicorn, sqlalchemy, aiosqlite |
| [04_advanced_features.py](04_advanced_features.py) | Ping, errors, separators, headers | fastapi, uvicorn |
| [05_memory_channels.py](05_memory_channels.py) | Memory channels (producer-consumer) | starlette, uvicorn |
| [06_send_timeout.py](06_send_timeout.py) | Frozen client detection | starlette, uvicorn |
| [07_cooperative_shutdown.py](07_cooperative_shutdown.py) | Graceful shutdown with farewell events | starlette, uvicorn |

## Running

Each example is self-contained:

    python examples/01_basic_sse.py

Then test with:

    curl -N http://localhost:8000/<endpoint>

See each file's docstring for specific endpoints and curl commands.
```

### Contracts

N/A — examples are standalone educational files with no external interfaces.

### Data Model

N/A — file reorganization task, no data entities.

### Quickstart

N/A — the README.md in the examples directory serves this purpose.

## Post-Phase 1 Constitution Re-Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Simplicity & YAGNI | **PASS** | 20+ files → 8 files (7 examples + README). No unnecessary abstraction. |
| II. Test-First | **N/A** | Not library code. Manual verification sufficient. |
| III. Async Correctness | **PASS** | All examples use `anyio` primitives. New 07 uses `anyio.Event`. |
| IV. Connection Lifecycle | **PASS** | Examples 01-07 collectively demonstrate the full lifecycle. |
| V. Backwards Compatibility | **N/A** | Examples are not API surface. |
| Governance | **PASS** | `make lint`, `make ty`, `make test-unit` verification included as Step 6. |

No violations. Plan is ready for `/speckit.tasks`.
