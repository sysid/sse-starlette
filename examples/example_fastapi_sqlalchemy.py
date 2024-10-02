import typing as T

import sqlalchemy as sa
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sse_starlette.sse import EventSourceResponse

# Database
db_bind = create_async_engine("sqlite+aiosqlite://:memory:")
AsyncSessionLocal = async_sessionmaker(bind=db_bind, expire_on_commit=False)


async def async_db_session():
    async with AsyncSessionLocal() as session:
        yield session


AsyncDbSessionDependency = T.Annotated[AsyncSession, Depends(async_db_session)]

TODOS_CTE_SQL = """
WITH todo AS (
    SELECT 1 AS id, 'Task 1' AS title, 'Description 1' AS description, 0 AS completed
    UNION ALL
    SELECT 2, 'Task 2', 'Description 2', 1
    UNION ALL
    SELECT 3, 'Task 3', 'Description 3', 0
)
"""

# App
app = FastAPI()


@app.route("/things")
async def things(db_session: AsyncDbSessionDependency):
    # Safe to use db_session here to do auth or something else.
    async def thing_streamer():
        # Do *NOT* reuse db_session here within the AsyncGenerator, create a
        # new session instead.
        async with AsyncSessionLocal() as session:
            async for row in session.execute(sa.text(TODOS_CTE_SQL)):
                yield {"data": dict(row)}

    return EventSourceResponse(thing_streamer)
