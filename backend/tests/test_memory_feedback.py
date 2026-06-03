import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, Memory
from app.services.memory_evolution import record_retrieval, record_usefulness

pytestmark = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="requires NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db",
)


def test_record_feedback_updates_scores():
    async def scenario():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        uid, m1, m2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with Session() as s:
            s.add(User(id=uid, name="t"))
            s.add(Memory(id=m1, user_id=uid, content="a"))
            s.add(Memory(id=m2, user_id=uid, content="b"))
            await s.commit()

        async with Session() as s:
            await record_retrieval(s, [m1, m2])
            await record_usefulness(s, retrieved_ids=[m1, m2], used_ids=[m1])

        async with Session() as s:
            a = await s.get(Memory, m1)
            b = await s.get(Memory, m2)
            assert a.retrieved_count == 1
            assert a.useful_count == 1
            assert b.retrieved_count == 1
            assert b.useful_count == 0
            assert a.utility_score > b.utility_score

        await engine.dispose()

    asyncio.run(scenario())
