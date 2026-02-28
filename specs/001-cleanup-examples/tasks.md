# Tasks: Cleanup and Consolidate Examples

**Input**: Design documents from `/specs/001-cleanup-examples/`
**Prerequisites**: plan.md (required), spec.md (required), research.md

**Tests**: Not applicable — examples are not library code. Verification is manual (run each example, confirm SSE events via curl).

**Organization**: Tasks are grouped by user story to enable incremental delivery. For this cleanup task, stories layer quality on top of the same structural work.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Promote and Preserve)

**Purpose**: Copy files out of subdirectories before deletion to prevent data loss.

- [x] T001 [P] Copy `examples/demonstrations/advanced_patterns/memory_channels.py` to `examples/05_memory_channels.py`
- [x] T002 [P] Copy `examples/demonstrations/production_scenarios/frozen_client.py` to `examples/06_send_timeout.py`

---

## Phase 2: Foundational (Remove and Restructure)

**Purpose**: Delete redundant files and directories. Create flat structure. MUST complete before user story work.

- [x] T003 Remove redundant root-level files: `examples/example.py`, `examples/stream_generator.py`, `examples/stream_generator_multiple.py`, `examples/demo_client.html`, `examples/example.db`
- [x] T004 Remove entire `examples/demonstrations/` directory (all subdirectories and contents)
- [x] T005 Remove entire `examples/issues/` directory (all contents)
- [x] T006 Rename `examples/02_message_broadcasting.py` to `examples/02_broadcasting.py` using `git mv`

**Checkpoint**: Flat directory with 6 Python files (01-06) and no subdirectories.

---

## Phase 3: User Story 1 - Find and Run Examples (Priority: P1) MVP

**Goal**: All 7 examples exist, run successfully, and serve SSE events via `curl -N`.

**Independent Test**: Run each example with `python examples/<file>.py`, then `curl -N http://localhost:8000/<endpoint>` — confirm SSE events received.

### Implementation for User Story 1

- [x] T007 [P] [US1] Update docstring and `__main__` block in `examples/05_memory_channels.py` to match kept examples' format (what it demonstrates, how to run, curl commands, startup messages)
- [x] T008 [P] [US1] Update docstring and `__main__` block in `examples/06_send_timeout.py` to match kept examples' format (what it demonstrates, how to run, curl commands, startup messages)
- [x] T009 [US1] Create `examples/07_cooperative_shutdown.py` demonstrating `shutdown_event` + `shutdown_grace_period` parameters (v3.3.0 API). Use the pattern from CLAUDE.md: generator checks `shutdown_event.is_set()`, yields farewell event on shutdown. Include consistent docstring with curl commands.
- [x] T010 [US1] Verify all 7 examples start successfully and serve SSE events (run each, test with curl, confirm no import errors or crashes)

**Checkpoint**: 7 working examples in flat directory. MVP complete.

---

## Phase 4: User Story 2 - Progressive Learning (Priority: P2)

**Goal**: Examples progress naturally from simple to advanced. Docstrings are consistent and educational.

**Independent Test**: Read examples 01 through 07 in order — each should build on concepts from previous ones without unexplained jumps.

### Implementation for User Story 2

- [x] T011 [US2] Merge conditional yield pattern from `examples/demonstrations/basic_patterns/main_endless_conditional.py` into `examples/01_basic_sse.py` as a third endpoint (conditional data availability pattern). Note: read source from git history since file was deleted in Phase 2 — or reference the already-read content from the spec analysis.
- [x] T012 [US2] Review and normalize all 7 example docstrings to consistent format: (1) module docstring with feature description, (2) "Usage:" section with run command, (3) "Test with curl:" section with endpoint-specific commands

**Checkpoint**: All examples form a progressive learning path with consistent documentation.

---

## Phase 5: User Story 3 - Professional Appearance (Priority: P3)

**Goal**: The examples directory looks clean and professional on GitHub.

**Independent Test**: Browse `examples/` on GitHub — no dead files, no binary artifacts, clear README with feature table.

### Implementation for User Story 3

- [x] T013 [US3] Write `examples/README.md` per plan.md README structure: title, prerequisites (core + optional deps), examples table (file, feature, dependencies), running instructions, curl testing guidance

**Checkpoint**: Professional README with feature mapping. Directory is clean.

---

## Phase 6: Polish & Verification

**Purpose**: Confirm all success criteria are met and no regressions introduced.

- [x] T014 Run `make lint` and fix any formatting issues in example files
- [x] T015 Run `make test-unit` and confirm all existing library tests still pass
- [x] T016 Verify success criteria: SC-001 (7 files + README), SC-002 (all run), SC-003 (distinct features), SC-004 (no binaries, no subdirectories)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (must copy before deleting)
- **US1 (Phase 3)**: Depends on Phase 2 (flat structure exists)
- **US2 (Phase 4)**: Depends on Phase 3 (examples exist and work)
- **US3 (Phase 5)**: Depends on Phase 3 (need final file list for README table)
- **Polish (Phase 6)**: Depends on all previous phases

### User Story Dependencies

- **US1 (P1)**: Core story — all others depend on it
- **US2 (P2)**: Can start after US1. Modifies files created/verified in US1.
- **US3 (P3)**: Can start after US1 (needs final file list). Parallel with US2.

### Parallel Opportunities

Within Phase 1: T001 and T002 operate on different files — run in parallel.
Within Phase 3: T007 and T008 operate on different files — run in parallel.
Phase 4 and Phase 5: US2 and US3 can run in parallel after US1 completes.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Promote files (T001-T002)
2. Phase 2: Remove and restructure (T003-T006)
3. Phase 3: Working examples (T007-T010)
4. **STOP and VALIDATE**: All 7 examples run and serve SSE events

### Incremental Delivery

1. Phases 1-3 → MVP: 7 working examples in flat directory
2. Phase 4 → Enhanced: Consistent docstrings, progressive learning, conditional yield merged
3. Phase 5 → Professional: README with feature table
4. Phase 6 → Verified: Lint, tests, success criteria confirmed

---

## Notes

- T011 (merge conditional yield) must account for `main_endless_conditional.py` being deleted in Phase 2. Read the file content before deletion or use the content already captured during spec analysis.
- Use `git mv` for T006 (rename) to preserve git history.
- Use `git rm` for tracked files in T003-T005 where applicable.
- T009 (cooperative shutdown) is the only net-new file. Pattern reference: CLAUDE.md § "Cooperative Shutdown (New in v3.3.0)".
