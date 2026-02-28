# Feature Specification: Cleanup and Consolidate Examples Directory

**Feature Branch**: `001-cleanup-examples`
**Created**: 2026-02-28
**Status**: Draft
**Input**: User description: "We need to cleanup and simplify the ./examples directory. We should only keep non-trivial examples which demonstrate an important feature. Make sure all kept examples actually work as intended. The documentation needs to be improved. Consolidate and make look it professional."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find and run a relevant example quickly (Priority: P1)

A developer integrating sse-starlette wants to find a working example that demonstrates a specific library feature. They browse the examples directory, identify the relevant file from its name and the README, and run it successfully.

**Why this priority**: The primary purpose of examples is to help users adopt the library. If examples are hard to find, redundant, or broken, they hurt adoption rather than help.

**Independent Test**: Can be verified by running each kept example with `python examples/<file>.py` and confirming it starts without errors and serves SSE events accessible via `curl -N`.

**Acceptance Scenarios**:

1. **Given** a developer looks at the examples directory, **When** they read the README, **Then** they can identify which example demonstrates the feature they need within 30 seconds.
2. **Given** a developer picks any example file, **When** they run it with `python examples/<file>.py`, **Then** the server starts and serves SSE events correctly.
3. **Given** the examples directory, **When** a developer lists its contents, **Then** there are no duplicate or near-duplicate files demonstrating the same concept.

---

### User Story 2 - Understand SSE patterns through progressive examples (Priority: P2)

A developer new to SSE wants to learn the library's features progressively: basic streaming first, then broadcasting, then advanced features like memory channels and database integration.

**Why this priority**: Good examples serve as documentation. A clear progression from simple to advanced reduces the learning curve.

**Independent Test**: Can be verified by reading examples in the order suggested by the README and confirming each builds on concepts from the previous one without unexplained jumps.

**Acceptance Scenarios**:

1. **Given** a developer reads examples in suggested order, **When** they reach an advanced example, **Then** all concepts used have been introduced in earlier examples.
2. **Given** any example file, **When** a developer reads its docstring, **Then** they understand what library feature it demonstrates and how to run/test it.

---

### User Story 3 - Professional appearance for open-source library (Priority: P3)

A potential contributor or evaluator browses the repository on GitHub. The examples directory looks clean, professional, and well-maintained — reinforcing confidence in the library.

**Why this priority**: First impressions matter for open-source adoption. A messy examples directory signals poor maintenance.

**Independent Test**: Can be verified by reviewing the examples directory on GitHub and confirming consistent naming, no dead files, no binary artifacts, and a clear README.

**Acceptance Scenarios**:

1. **Given** the examples directory, **When** viewed on GitHub, **Then** there are no binary files (`.db`), no orphaned HTML files, and no empty subdirectories.
2. **Given** the examples README, **When** read on GitHub, **Then** it renders correctly with a clear table of contents linking each example to the feature it demonstrates.

---

### Edge Cases

- Examples that import optional dependencies (e.g., `sqlalchemy`, `pydantic`) must note which extras are required in their docstring and in the README.
- Examples referencing internal APIs (e.g., `AppStatus._initialized`) must be removed or rewritten to use only public APIs.
- Examples with bugs (e.g., `graceful_shutdown.py` uses `time.sleep` in signal handler, `no_async_generators.py` has dead trio code) must be fixed or removed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each kept example MUST run successfully with `python examples/<file>.py` and serve SSE events accessible via `curl -N`.
- **FR-002**: Each kept example MUST demonstrate a distinct, non-trivial library feature — no two examples may demonstrate the same primary concept.
- **FR-003**: Each example file MUST have a docstring explaining: what feature it demonstrates, how to run it, and how to test it with curl.
- **FR-004**: The examples directory MUST have a README.md with a table mapping each example to the library feature it demonstrates.
- **FR-005**: Examples MUST NOT contain binary artifacts (`.db` files), dead code, or references to internal/private APIs.
- **FR-006**: Examples using optional dependencies (e.g., `sqlalchemy`, `pydantic`) MUST document those dependencies in their docstring and in the README.
- **FR-007**: A flat directory structure MUST be used — no nested subdirectories. Each example is a self-contained file.
- **FR-008**: Redundant examples MUST be removed. Unique patterns from removed files MUST be preserved by merging into kept examples where appropriate.

### Inventory: Current Files and Disposition

The following table documents the analysis of all current files:

| File | Feature Demonstrated | Disposition | Reason |
|------|---------------------|-------------|--------|
| `example.py` | Basic SSE + HTML client | **REMOVE** | Overlaps with 01_basic_sse; inline HTML is not an SSE server feature |
| `01_basic_sse.py` | Basic streaming (Starlette + FastAPI) | **KEEP** | Good intro, covers both frameworks |
| `02_message_broadcasting.py` | Queue-based multi-client broadcasting | **KEEP** | Non-trivial, key broadcasting pattern |
| `03_database_streaming.py` | Thread-safe DB sessions in SSE generators | **KEEP** | Critical pitfall documentation |
| `04_advanced_features.py` | Ping, error handling, separators, headers | **KEEP** | Covers multiple library API features |
| `stream_generator.py` | Single-client queue push | **REMOVE** | Superseded by 02_message_broadcasting |
| `stream_generator_multiple.py` | Multi-stream broadcasting | **REMOVE** | Superseded by 02_message_broadcasting |
| `demo_client.html` | HTML/JS EventSource client | **REMOVE** | Not an SSE server example |
| `example.db` | None | **REMOVE** | Binary artifact |
| `demonstrations/conftest.py` | None | **REMOVE** | Not used as actual tests |
| `demonstrations/README.md` | None | **REMOVE** | Replaced by new root README |
| `demonstrations/basic_patterns/client_disconnect.py` | Connection tracking | **REMOVE** | Pattern covered in 01 and 04 |
| `demonstrations/basic_patterns/graceful_shutdown.py` | Shutdown handling | **REMOVE** | Has bugs; library handles shutdown internally |
| `demonstrations/basic_patterns/main_endless_conditional.py` | Conditional yield + shutdown | **MERGE into 01** | Unique pattern worth preserving |
| `demonstrations/advanced_patterns/custom_protocols.py` | Custom event types | **REMOVE** | Over-engineered; application logic, not library features |
| `demonstrations/advanced_patterns/error_recovery.py` | Error handling patterns | **REMOVE** | Application-level; error handling already in 04 |
| `demonstrations/advanced_patterns/memory_channels.py` | `data_sender_callable` with anyio channels | **KEEP as 05** | Key library API |
| `demonstrations/production_scenarios/frozen_client.py` | `send_timeout` feature | **KEEP as 06** | Unique library feature |
| `demonstrations/production_scenarios/load_simulations.py` | Load testing | **REMOVE** | Not demonstrating library features |
| `demonstrations/production_scenarios/network_interruption.py` | Network simulation | **REMOVE** | Client-side patterns, not SSE library features |
| `issues/issue132_fix.py` | Signal handling demo | **REMOVE** | 648 lines of bloat; covered by test suite |
| `issues/issue132.py` | Shutdown reproduction | **REMOVE** | Covered by regression tests |
| `issues/issue152.py` | Watcher leak test | **REMOVE** | Covered by test_issue152.py |
| `issues/issue77.py` | Lock contention load test | **REMOVE** | Benchmarking, not feature demonstration |
| `issues/no_async_generators.py` | Memory channel alternative | **REMOVE** | Has dead trio code; covered by promoted memory_channels.py |

### Resulting Examples (7 files + README)

| # | File | Library Feature |
|---|------|----------------|
| 1 | `01_basic_sse.py` | Basic streaming, Starlette + FastAPI, finite/endless/conditional streams |
| 2 | `02_broadcasting.py` | Queue-based multi-client broadcasting with async iterator protocol |
| 3 | `03_database_streaming.py` | Thread-safe database sessions in SSE generators |
| 4 | `04_advanced_features.py` | Custom ping, error handling, line separators, proxy headers, background tasks |
| 5 | `05_memory_channels.py` | `data_sender_callable` with anyio memory channels, producer-consumer pattern |
| 6 | `06_send_timeout.py` | `send_timeout` for frozen/slow client detection |
| 7 | `07_cooperative_shutdown.py` | `shutdown_event` + `shutdown_grace_period` for farewell events before server shutdown (v3.3.0) |
| - | `README.md` | Index with feature mapping, prerequisites, and running instructions |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The examples directory contains exactly 7 Python files and 1 README — down from 20+ files across 4 directories.
- **SC-002**: All 7 examples start successfully and serve SSE events when run with `python examples/<file>.py`.
- **SC-003**: No two examples demonstrate the same primary library feature.
- **SC-004**: The examples directory contains zero binary files, zero empty directories, and zero subdirectories.

## Assumptions

- The `demonstrations/` and `issues/` subdirectories can be fully removed because their unique content is either merged into kept examples or already covered by the test suite.
- The `03_database_streaming.py` example keeps its SQLAlchemy dependency because the thread-safety pitfall is too important to lose. The README will note this as an optional dependency.
- The conditional yield pattern from `main_endless_conditional.py` will be merged into `01_basic_sse.py` as an additional endpoint.
- `07_cooperative_shutdown.py` is a new example (not derived from any existing file) demonstrating the v3.3.0 `shutdown_event` and `shutdown_grace_period` parameters. The pattern is documented in the project CLAUDE.md under "Cooperative Shutdown."
