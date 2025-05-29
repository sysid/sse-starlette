"""
Database streaming example showing thread-safe patterns with aiosqlite.

This example demonstrates:
- Thread-safe database session management in SSE streams
- Streaming database query results
- Proper connection cleanup and error handling
- Simple async database operations

Dependencies:
    pip install aiosqlite

Usage:
    python 03_database_streaming.py

Test with curl:
    # Stream all tasks
    curl -N http://localhost:8000/tasks/stream

    # Stream tasks with status filter
    curl -N http://localhost:8000/tasks/stream?completed=true
    curl -N http://localhost:8000/tasks/stream?completed=false

    # Stream with pagination
    curl -N http://localhost:8000/tasks/stream?limit=2
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional, Dict, Any

import aiosqlite
import uvicorn
from fastapi import FastAPI, Query
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from sse_starlette import EventSourceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DATABASE_PATH = Path("./example.db")


class DatabaseManager:
    """Simple database manager for demonstration purposes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def init_database(self):
        """Initialize database with sample data."""
        async with aiosqlite.connect(self.db_path) as db:
            # Create table
            await db.execute("""
                             CREATE TABLE IF NOT EXISTS tasks
                             (
                                 id
                                 INTEGER
                                 PRIMARY
                                 KEY
                                 AUTOINCREMENT,
                                 title
                                 TEXT
                                 NOT
                                 NULL,
                                 description
                                 TEXT,
                                 completed
                                 BOOLEAN
                                 DEFAULT
                                 FALSE
                             )
                             """)

            # Check if we need to insert sample data
            cursor = await db.execute("SELECT COUNT(*) FROM tasks")
            count = await cursor.fetchone()

            if count[0] == 0:
                sample_tasks = [
                    ("Learn FastAPI", "Study FastAPI documentation", False),
                    ("Build SSE app", "Create server-sent events application", True),
                    ("Write tests", "Add comprehensive test coverage", False),
                    ("Deploy to production", "Set up CI/CD pipeline", False),
                    ("Monitor performance", "Set up logging and metrics", True),
                ]

                await db.executemany(
                    "INSERT INTO tasks (title, description, completed) VALUES (?, ?, ?)",
                    sample_tasks
                )
                await db.commit()
                logger.info("Inserted sample tasks into database")

    async def get_tasks(self, completed_filter: Optional[bool] = None, limit: Optional[int] = None) -> list:
        """Get tasks with optional filtering."""
        query = "SELECT id, title, description, completed FROM tasks"
        params = []

        if completed_filter is not None:
            query += " WHERE completed = ?"
            params.append(completed_filter)

        query += " ORDER BY id"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row  # Enable dict-like access
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_task_count(self) -> int:
        """Get total number of tasks."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM tasks")
            count = await cursor.fetchone()
            return count[0]


# Global database manager
db_manager = DatabaseManager(DATABASE_PATH)


async def stream_tasks_safely(
    request: Request,
    completed_filter: Optional[bool] = None,
    limit: Optional[int] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    CORRECT: Stream tasks with proper connection management.
    Each database operation uses its own connection within the generator.
    This is the recommended pattern for SSE with databases.
    """
    try:
        # Get tasks using a dedicated connection - THREAD SAFE
        tasks = await db_manager.get_tasks(completed_filter, limit)

        for task in tasks:
            # Check for client disconnect before each task
            if await request.is_disconnected():
                logger.info("Client disconnected, stopping task stream")
                break

            yield {
                "data": {
                    "id": task["id"],
                    "title": task["title"],
                    "description": task["description"],
                    "completed": bool(task["completed"])
                },
                "event": "task",
                "id": str(task["id"])
            }

            # Add delay to simulate streaming behavior
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Error streaming tasks: {e}")
        yield {
            "data": {"error": "Failed to stream tasks", "details": str(e)},
            "event": "error"
        }


async def stream_tasks_with_live_updates(request: Request) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Advanced example: Stream tasks with simulated live updates.
    This demonstrates how you might handle real-time database changes.
    """
    try:
        # First, stream existing tasks
        tasks = await db_manager.get_tasks()

        for task in tasks:
            if await request.is_disconnected():
                break

            yield {
                "data": task,
                "event": "existing_task",
                "id": f"existing_{task['id']}"
            }
            await asyncio.sleep(0.3)

        # Then simulate live updates (in a real app, this might come from a message queue)
        update_counter = 0
        while not await request.is_disconnected():
            update_counter += 1

            # Simulate different types of updates
            if update_counter % 3 == 0:
                yield {
                    "data": {
                        "message": f"System check #{update_counter // 3}",
                        "timestamp": asyncio.get_event_loop().time()
                    },
                    "event": "system_update"
                }
            else:
                yield {
                    "data": {
                        "message": f"Database activity detected (simulated #{update_counter})",
                        "active_connections": 1
                    },
                    "event": "activity_update"
                }

            await asyncio.sleep(2.0)

    except asyncio.CancelledError:
        logger.info("Task streaming cancelled by client disconnect")
        raise
    except Exception as e:
        logger.error(f"Error in live updates stream: {e}")
        yield {
            "data": {"error": "Live updates failed", "details": str(e)},
            "event": "error"
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    # Startup
    await db_manager.init_database()
    logger.info("Database initialized with sample tasks")
    yield
    # Shutdown - aiosqlite connections are automatically closed
    logger.info("Application shutdown complete")


app = FastAPI(title="SSE Database Streaming", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/tasks/stream")
async def stream_tasks_endpoint(
    request: Request,
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    limit: Optional[int] = Query(None, description="Limit number of results")
) -> EventSourceResponse:
    """Stream tasks from the database with optional filters."""
    return EventSourceResponse(
        stream_tasks_safely(request, completed, limit),
        headers={"X-Stream-Type": "database"}
    )


@app.get("/tasks/live")
async def stream_live_updates_endpoint(request: Request) -> EventSourceResponse:
    """Stream tasks with simulated live updates."""
    return EventSourceResponse(
        stream_tasks_with_live_updates(request),
        headers={"X-Stream-Type": "live_database"},
        ping=10  # Ping every 10 seconds for long-running streams
    )


@app.get("/tasks/count")
async def get_task_count() -> Dict[str, int]:
    """Get total task count (for demonstration)."""
    count = await db_manager.get_task_count()
    return {"total_tasks": count}


@app.get("/tasks/list")
async def list_tasks(
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    limit: Optional[int] = Query(None, description="Limit number of results")
) -> Dict[str, Any]:
    """Get tasks as regular JSON (non-streaming) for comparison."""
    tasks = await db_manager.get_tasks(completed, limit)
    return {
        "tasks": tasks,
        "count": len(tasks),
        "filtered": completed is not None
    }


if __name__ == "__main__":
    print("Starting SSE database streaming server...")
    print("Available endpoints:")
    print("  - GET http://localhost:8000/tasks/stream (stream all tasks)")
    print("  - GET http://localhost:8000/tasks/stream?completed=true (stream completed tasks)")
    print("  - GET http://localhost:8000/tasks/stream?limit=3 (limit results)")
    print("  - GET http://localhost:8000/tasks/live (stream with live updates)")
    print("  - GET http://localhost:8000/tasks/count (get task count)")
    print("  - GET http://localhost:8000/tasks/list (get tasks as JSON)")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
