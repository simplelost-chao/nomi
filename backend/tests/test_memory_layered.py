"""Integration tests for MemoryService.search_memories_layered / _search_layer.

Guarded to run only when NOMI_DATABASE_URL points to sqlite (in-memory engine),
mirroring the pattern in test_memory_feedback.py.
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, Memory

pytestmark = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="requires NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db",
)


class _FakeLLM:
    """Minimal LLM stub that returns a fixed embedding for any text."""
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def test_layered_search_respects_budget_and_excludes_archived():
    async def scenario():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        uid = uuid.uuid4()
        owner = uuid.uuid4()
        emb = [1.0, 0.0, 0.0]

        async with Session() as s:
            s.add(User(id=uid, name="t"))
            # 3 episodic memories (1 archived)
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="episodic 1", memory_layer="episodic",
                         embedding=emb, archived=False))
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="episodic 2", memory_layer="episodic",
                         embedding=emb, archived=False))
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="episodic archived", memory_layer="episodic",
                         embedding=emb, archived=True))
            # 2 principle memories
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="principle 1", memory_layer="principle",
                         embedding=emb, archived=False))
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="principle 2", memory_layer="principle",
                         embedding=emb, archived=False))
            # 1 semantic memory
            s.add(Memory(id=uuid.uuid4(), user_id=uid, owner_id=owner,
                         content="semantic 1", memory_layer="semantic",
                         embedding=emb, archived=False))
            await s.commit()

        from app.services.memory import MemoryService

        async with Session() as s:
            svc = MemoryService(session=s, llm=_FakeLLM())
            # Budget: 1 principle, 1 semantic, 1 episodic
            results = await svc.search_memories_layered(
                query="anything",
                user_id=uid,
                owner_id=owner,
                budget={"principle": 1, "semantic": 1, "episodic": 1},
            )

        # Total should be 3 (1 per layer)
        assert len(results) == 3

        layers_returned = {m.memory_layer for m in results}
        assert layers_returned == {"principle", "semantic", "episodic"}

        # Archived memory must not appear
        contents = {m.content for m in results}
        assert "episodic archived" not in contents

        await engine.dispose()

    asyncio.run(scenario())


def test_search_layer_zero_budget_returns_empty():
    async def scenario():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        uid = uuid.uuid4()
        async with Session() as s:
            s.add(User(id=uid, name="t"))
            await s.commit()

        from app.services.memory import MemoryService

        async with Session() as s:
            svc = MemoryService(session=s, llm=_FakeLLM())
            results = await svc.search_memories_layered(
                query="anything",
                user_id=uid,
                owner_id=None,
                budget={"principle": 0, "semantic": 0, "episodic": 0},
            )
        assert results == []
        await engine.dispose()

    asyncio.run(scenario())
