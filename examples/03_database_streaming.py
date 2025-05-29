"""
Database Streaming Example - Thread-safe SQLAlchemy session management in SSE

This example demonstrates:
- CORRECT: Create database sessions within generators (thread-safe)
- INCORRECT: Reusing sessions across task boundaries (thread-unsafe)
- Streaming query results with proper async session management
- Clean separation of concerns between endpoint logic and data streaming

CRITICAL SESSION RULE: Never reuse database sessions between async tasks.
Always create new sessions within generators that will run in task groups.

Usage:
    python 03_database_streaming.py

Test with curl:
    # Stream all tasks
    curl -N http://localhost:8000/tasks/stream

    # Stream with filters
    curl -N http://localhost:8000/tasks/stream?completed=true
    curl -N http://localhost:8000/tasks/stream?completed=false
    curl -N http://localhost:8000/tasks/stream?limit=3

    # Compare with regular JSON endpoint
    curl http://localhost:8000/tasks/list
"""

import asyncio
import typing as T
from typing import AsyncGenerator, Optional

import sqlalchemy as sa
import uvicorn
from fastapi import Depends, FastAPI, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from sse_starlette import EventSourceResponse

db_bind = create_async_engine("sqlite+aiosqlite:///:memory:")
AsyncSessionLocal = async_sessionmaker(bind=db_bind, expire_on_commit=False)


# Dependency for regular endpoints (NOT for use in generators)
async def async_db_session():
    """
    Standard dependency for regular endpoints.

    IMPORTANT: Do NOT use this dependency in SSE generators.
    The session created here runs in the main request context,
    but generators run in separate tasks within anyio task groups.
    """
    async with AsyncSessionLocal() as session:
        yield session


AsyncDbSessionDependency = T.Annotated[AsyncSession, Depends(async_db_session)]

TODOS_CTE_SQL = """
                WITH todo AS (SELECT 1                               AS id,
                                     'Implement SSE streaming'       AS title,
                                     'Add server-sent events to API' AS description,
                                     0                               AS completed
                              UNION ALL
                              SELECT 2, 'Database integration', 'Connect SQLAlchemy with SSE', 1
                              UNION ALL
                              SELECT 3, 'Add filtering', 'Support query parameters in streams', 0
                              UNION ALL
                              SELECT 4, 'Write documentation', 'Document best practices', 1
                              UNION ALL
                              SELECT 5, 'Performance testing', 'Test with large datasets', 0)
                SELECT *
                FROM todo
                """

app = FastAPI()


class TaskDatabaseStream:
    """
    Stream that yields database query results as SSE events.

    Key design decisions:
    1. Create dedicated session within the generator (thread-safe)
    2. Apply filters inside the database query (efficient)
    3. Implement proper async iteration protocol
    4. Handle client disconnection gracefully
    """

    def __init__(self, request: Request, completed_filter: Optional[bool] = None, limit: Optional[int] = None):
        self.request = request
        self.completed_filter = completed_filter
        self.limit = limit

    def __aiter__(self) -> "TaskDatabaseStream":
        return self

    async def __anext__(self) -> dict:
        """
        Lazy evaluation: Database query happens here, not in __init__.

        This ensures the query runs within the correct async context
        and uses a fresh session created specifically for this stream.
        """
        if not hasattr(self, '_results'):
            await self._execute_query()
            self._index = 0

        if self._index >= len(self._results):
            raise StopAsyncIteration

        if await self.request.is_disconnected():
            raise StopAsyncIteration

        result = self._results[self._index]
        self._index += 1

        # Add small delay to demonstrate streaming behavior
        await asyncio.sleep(0.3)

        return {
            "data": {
                "id": result.id,
                "title": result.title,
                "description": result.description,
                "completed": bool(result.completed)
            },
            "event": "task",
            "id": str(result.id)
        }

    async def _execute_query(self):
        """
        CORRECT PATTERN: Create session within the generator context.

        This session is created in the same async context where the
        generator will yield results, ensuring thread safety with
        anyio task groups used by EventSourceResponse.

        Always create new sessions within generators, never reuse sessions from dependency injection.
        """
        async with AsyncSessionLocal() as session:
            # Build query with filters - using sa.text() for raw SQL
            query = TODOS_CTE_SQL

            if self.completed_filter is not None:
                query += " WHERE completed = :completed"

            query += " ORDER BY id"

            if self.limit:
                query += " LIMIT :limit"

            # Prepare parameters for SQLAlchemy
            params = {}
            if self.completed_filter is not None:
                params['completed'] = int(self.completed_filter)
            if self.limit:
                params['limit'] = self.limit

            # Execute query using async iteration pattern from example
            result = await session.execute(sa.text(query), params)
            self._results = result.fetchall()


async def correct_task_stream(request: Request, completed: Optional[bool] = None, limit: Optional[int] = None) -> AsyncGenerator[dict, None]:
    """
    CORRECT: Alternative implementation using async generator function.

    This demonstrates the same thread-safe pattern using a function
    instead of a class. The key principle remains: create the session
    within the generator scope.

    "Do *NOT* reuse db_session here within the AsyncGenerator, create a new session instead."
    """
    # Session created INSIDE the generator - this is safe
    async with AsyncSessionLocal() as session:
        query = TODOS_CTE_SQL
        params = {}

        if completed is not None:
            query += " WHERE completed = :completed"
            params['completed'] = int(completed)

        query += " ORDER BY id"

        if limit:
            query += " LIMIT :limit"
            params['limit'] = limit

        # Execute query and iterate over results
        result = await session.execute(sa.text(query), params)
        rows = result.fetchall()

        for row in rows:
            if await request.is_disconnected():
                break

            yield {
                "data": {
                    "id": row.id,
                    "title": row.title,
                    "description": row.description,
                    "completed": bool(row.completed)
                },
                "event": "task",
                "id": str(row.id)
            }

            await asyncio.sleep(0.3)


async def incorrect_task_stream_example(session: AsyncSession, request: Request) -> AsyncGenerator[dict, None]:
    """
    INCORRECT: This pattern will cause issues with anyio task groups.

    The session parameter comes from the dependency injection system,
    which runs in the main request context. However, this generator
    will be consumed by EventSourceResponse within an anyio task group,
    creating a cross-task session usage that can cause threading issues.

    DO NOT USE THIS PATTERN - included only for educational purposes.
    """
    # This query would fail because session is from different async context
    result = await session.execute(sa.text(TODOS_CTE_SQL))
    rows = result.fetchall()

    for row in rows:
        yield {"data": dict(row._mapping), "event": "task"}


@app.get("/tasks/stream")
async def stream_tasks_endpoint(
    request: Request,
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    limit: Optional[int] = Query(None, description="Limit number of results")
) -> EventSourceResponse:
    """
    SSE endpoint that streams database query results.

    Notice: We do NOT inject a database session here because the session
    must be created within the generator context for thread safety.
    """
    stream = TaskDatabaseStream(request, completed, limit)
    return EventSourceResponse(stream)


@app.get("/tasks/stream-function")
async def stream_tasks_function_endpoint(
    request: Request,
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    limit: Optional[int] = Query(None, description="Limit number of results")
) -> EventSourceResponse:
    """
    Alternative SSE endpoint using generator function instead of class.

    Both approaches are valid - choose based on complexity of your logic.
    Classes are better for stateful streaming, functions for simple cases.
    """
    return EventSourceResponse(correct_task_stream(request, completed, limit))


@app.get("/tasks/list")
async def list_tasks_endpoint(
    session: AsyncDbSessionDependency,
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    limit: Optional[int] = Query(None, description="Limit number of results")
) -> dict:
    """
    Regular JSON endpoint - safe to use dependency injection.

    This demonstrates the CORRECT use of session dependency for
    regular endpoints vs the INCORRECT use in SSE generators.
    """
    query = TODOS_CTE_SQL
    params = {}

    if completed is not None:
        query += " WHERE completed = :completed"
        params['completed'] = int(completed)

    query += " ORDER BY id"

    if limit:
        query += " LIMIT :limit"
        params['limit'] = limit

    result = await session.execute(sa.text(query), params)
    rows = result.fetchall()

    return {
        "tasks": [dict(row._mapping) for row in rows],
        "total": len(rows),
        "streaming_available": True
    }


@app.get("/status")
async def status_endpoint():
    """Simple status endpoint."""
    return {"status": "ready", "database": "in-memory", "streaming": "enabled"}


if __name__ == "__main__":
    print("Database Streaming SSE Server")
    print("Stream all:      curl -N http://localhost:8000/tasks/stream")
    print("Stream filtered: curl -N http://localhost:8000/tasks/stream?completed=true")
    print("JSON endpoint:   curl http://localhost:8000/tasks/list")

    uvicorn.run(app, host="127.0.0.1", port=8000)
