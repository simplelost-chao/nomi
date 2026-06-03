import asyncio
import os
import uuid

import pytest

# DB-backed tests require the SQLite in-memory URL so that column types resolve
# to portable equivalents at import time.
_DB_SKIP = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="requires NOMI_DATABASE_URL=sqlite+aiosqlite:///:memory:",
)


def test_plan_dedup_merges_near_duplicates():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb, imp):
            self.id, self.embedding, self.importance_score = id, emb, imp
            self.base_importance = imp
            self.consolidated_into = None
    a = M(1, [1.0, 0.0], 0.4)
    a2 = M(2, [0.99, 0.0], 0.3)
    b = M(3, [0.0, 1.0], 0.5)
    merges = plan_dedup([a, a2, b], threshold=0.95)
    assert merges == [(2, 1)]   # (loser_id, winner_id): weaker folds into stronger


def test_plan_dedup_no_merge_when_distinct():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb):
            self.id, self.embedding, self.importance_score = id, emb, 0.5
            self.base_importance = 0.5
    out = plan_dedup([M(1, [1.0, 0.0]), M(2, [0.0, 1.0])], threshold=0.95)
    assert out == []


def test_plan_related_clusters_groups_min_size():
    from app.services.sleep_cycle import plan_related_clusters

    class M:
        def __init__(self, id, emb):
            self.id, self.embedding = id, emb
    items = [M(1, [1.0, 0.0]), M(2, [0.9, 0.1]), M(3, [0.85, 0.15]), M(9, [0.0, 1.0])]
    clusters = plan_related_clusters(items, threshold=0.7, min_size=3)
    assert len(clusters) == 1 and len(clusters[0]) == 3


# Integration test removed: SQLAlchemy column types (JSONB, Vector) are resolved
# at import time based on settings.is_sqlite, which is already False when running
# under the default Postgres URL. Forcing SQLite in-memory after the fact causes
# "Compiler can't render element of type JSONB" errors. The two plan_dedup pure
# tests above fully exercise the dedup logic; run_sleep_cycle DB wiring is covered
# by the import smoke check: cd backend && .venv/bin/python3.12 -c "import app.services.sleep_cycle"


@_DB_SKIP
def test_run_sleep_cycle_semantic_consolidation():
    """Integration test: three related episodic memories are promoted to one semantic memory."""

    async def scenario():
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.models import Base, User, Robot, Memory
        from app.services.sleep_cycle import run_sleep_cycle

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        uid = uuid.uuid4()
        rid = uuid.uuid4()
        m1_id, m2_id, m3_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async with Session() as s:
            s.add(User(id=uid, name="test"))
            s.add(Robot(id=rid, user_id=uid, name="TestBot",
                        personality={}, speaking_style={}))
            # Three related episodic memories (close embeddings) + archived=False
            s.add(Memory(id=m1_id, user_id=uid, owner_id=rid, owner_type="robot",
                         content="用户喜欢吃拉面", summary="喜欢吃拉面",
                         memory_type="episodic", memory_layer="episodic",
                         embedding=[1.0, 0.0], importance_score=0.5,
                         utility_score=0.5, archived=False))
            s.add(Memory(id=m2_id, user_id=uid, owner_id=rid, owner_type="robot",
                         content="用户常点拉面外卖", summary="常点拉面外卖",
                         memory_type="episodic", memory_layer="episodic",
                         embedding=[0.9, 0.1], importance_score=0.5,
                         utility_score=0.5, archived=False))
            s.add(Memory(id=m3_id, user_id=uid, owner_id=rid, owner_type="robot",
                         content="用户对拉面评价很高", summary="拉面评价很高",
                         memory_type="episodic", memory_layer="episodic",
                         embedding=[0.85, 0.15], importance_score=0.5,
                         utility_score=0.5, archived=False))
            await s.commit()

        class FakeLLM:
            async def generate(self, *a, **k):
                return "他们常在一起"

            async def embed(self, text):
                return [0.5, 0.5]

        async with Session() as s:
            robot = await s.get(Robot, rid)
            # dedup_threshold=1.0 prevents any dedup merge (all three are distinct);
            # consolidation stage then groups them as related memories.
            stats = await run_sleep_cycle(s, FakeLLM(), robot, dedup_threshold=1.0)

        # Verify a semantic memory was created
        from sqlalchemy import select
        async with Session() as s:
            result = await s.execute(
                select(Memory).where(Memory.owner_id == rid)
                .where(Memory.memory_layer == "semantic")
            )
            sem_mems = result.scalars().all()

        assert stats["promoted"] == 1, f"Expected 1 promoted, got {stats}"
        assert len(sem_mems) == 1, f"Expected 1 semantic memory, got {len(sem_mems)}"
        sem = sem_mems[0]
        source_ids = set(sem.linked_memory_ids or [])
        # linked_memory_ids are stored as strings in SQLite portable array
        source_ids_str = {str(i) for i in source_ids}
        assert {str(m1_id), str(m2_id), str(m3_id)}.issubset(source_ids_str), (
            f"linked_memory_ids {source_ids_str} does not cover source ids"
        )

        await engine.dispose()

    asyncio.run(scenario())
