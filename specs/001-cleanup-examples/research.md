# Research: Cleanup and Consolidate Examples

**Date**: 2026-02-28 | **Branch**: `001-cleanup-examples`

## R1: Do kept examples (01-04) run without modification?

- **Decision**: Keep as-is. No code changes needed for 03 and 04. Minor changes for 01 (merge conditional pattern) and 02 (rename).
- **Rationale**: All imports use public APIs. Dependencies are already declared in `pyproject.toml` optional groups.
- **Alternatives considered**: Rewriting examples to avoid FastAPI dependency → rejected, FastAPI is the primary use case for this library.

## R2: Do promoted examples need changes?

- **Decision**: Minimal changes — rename files, update docstrings to match kept examples' format, add startup messages.
- **Rationale**: The code logic is sound. `memory_channels.py` uses correct `anyio` APIs and `data_sender_callable`. `frozen_client.py` correctly demonstrates `send_timeout`.
- **Alternatives considered**: Rewriting from scratch → rejected, existing code works and is well-commented.

## R3: Cooperative shutdown example design

- **Decision**: New file `07_cooperative_shutdown.py` using the v3.3.0 API (`shutdown_event` + `shutdown_grace_period`).
- **Rationale**: This is the flagship v3.3.0 feature with no existing example. The pattern is documented in the project CLAUDE.md.
- **Alternatives considered**: Adding shutdown to an existing example (e.g., 01) → rejected, it's a distinct feature worthy of its own focused example.

## R4: File rename strategy

- **Decision**: `02_message_broadcasting.py` → `02_broadcasting.py`. Use `git mv` for tracked files.
- **Rationale**: Shorter name, `_message_` is redundant.
- **Alternatives considered**: Keeping original name → acceptable but inconsistent with the shorter naming style of other files.

## R5: Conditional yield merge into 01

- **Decision**: Add a third endpoint to `01_basic_sse.py` showing the conditional yield pattern from `main_endless_conditional.py`.
- **Rationale**: The pattern (generator that only yields when data is available, sleeping between checks) is a common real-world need. It fits naturally as a "basic pattern" alongside finite and endless streams.
- **Alternatives considered**: Separate file → rejected, too trivial for its own file; it's a variation of basic streaming.
