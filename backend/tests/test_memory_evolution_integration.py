"""Integration test for check_evolution principle-driven evolution with drift detection.

Guarded behind NOMI_DATABASE_URL containing "sqlite" so it is skipped in
environments without aiosqlite (mirrors pattern from test_memory_feedback.py).
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, Robot, Memory
from app.services.memory_evolution import check_evolution

pytestmark = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="requires NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db",
)


class _FakeLLM:
    """Fake LLM: generate returns a wildly different portrait_summary;
    embed returns [1,0] for text containing '平静' and [0,1] otherwise
    — so drift(平静温和 vs 暴躁好斗) > 0.35.
    """

    async def generate_structured(self, messages):
        return {
            "personality": ["aggressive", "belligerent"],
            "portrait_summary": "暴躁好斗",
            "emotional_baseline": "愤怒",
        }

    async def embed(self, text: str):
        if "平静" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


def test_check_evolution_rejects_unsupported_drift():
    """Mature robot (>= 2 total principles) with drift > 0.35 but only 1 backing
    principle (confidence >= 0.5) → evolution rejected.

    Setup: robot has portrait summary '平静温和'; fake LLM returns '暴躁好斗'.
    embed maps these to orthogonal vectors → drift ≈ 1.0.
    Robot has 2 principles total (mature), but only 1 has confidence >= 0.5
    → coherence gate fires → check_evolution must return False.
    """
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
        rid = uuid.uuid4()
        # robot.updated_at is set to past so new memories are "after" it
        past = datetime(2020, 1, 1)

        async with Session() as s:
            s.add(User(id=uid, name="tester"))
            robot = Robot(
                id=rid,
                user_id=uid,
                name="TestBot",
                portrait={"summary": "平静温和"},
                updated_at=past,
                created_at=past,
            )
            s.add(robot)
            # Add 10 new memories to trigger should_evolve
            for i in range(10):
                s.add(Memory(
                    id=uuid.uuid4(),
                    user_id=uid,
                    owner_type="robot",
                    owner_id=rid,
                    content=f"memory {i}",
                    importance_score=0.3,
                    memory_layer="episodic",
                    created_at=datetime.utcnow(),
                ))
            # Two principle memories total (mature robot), but only 1 has confidence >= 0.5
            # → mature=True, backing_principles=1 < 2 → gate fires → rejected
            s.add(Memory(
                id=uuid.uuid4(),
                user_id=uid,
                owner_type="robot",
                owner_id=rid,
                content="principle memory high",
                summary="core value high",
                importance_score=0.9,
                memory_layer="principle",
                archived=False,
                created_at=datetime.utcnow(),
            ))
            s.add(Memory(
                id=uuid.uuid4(),
                user_id=uid,
                owner_type="robot",
                owner_id=rid,
                content="principle memory low",
                summary="core value low",
                importance_score=0.2,  # below 0.5 threshold → not a backing principle
                memory_layer="principle",
                archived=False,
                created_at=datetime.utcnow(),
            ))
            await s.commit()

        async with Session() as s:
            robot = await s.get(Robot, rid)
            result = await check_evolution(s, _FakeLLM(), robot)

        await engine.dispose()
        return result

    result = asyncio.run(scenario())
    # Mature robot, drift > 0.35, but only 1 backing principle (< 2) → rejected
    assert result is False, f"Expected False (rejected), got {result}"


def test_check_evolution_accepts_with_two_backing_principles():
    """Two principles each with confidence >= 0.5, drift > 0.35 → evolution proceeds,
    portrait gains a 'history' entry with the old summary.
    """
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
        rid = uuid.uuid4()
        past = datetime(2020, 1, 1)

        async with Session() as s:
            s.add(User(id=uid, name="tester2"))
            robot = Robot(
                id=rid,
                user_id=uid,
                name="TestBot2",
                portrait={"summary": "平静温和"},
                updated_at=past,
                created_at=past,
            )
            s.add(robot)
            # 10 new memories to trigger should_evolve
            for i in range(10):
                s.add(Memory(
                    id=uuid.uuid4(),
                    user_id=uid,
                    owner_type="robot",
                    owner_id=rid,
                    content=f"memory {i}",
                    importance_score=0.3,
                    memory_layer="episodic",
                    created_at=datetime.utcnow(),
                ))
            # Two principle memories with confidence >= 0.5
            for i in range(2):
                s.add(Memory(
                    id=uuid.uuid4(),
                    user_id=uid,
                    owner_type="robot",
                    owner_id=rid,
                    content=f"principle {i}",
                    summary=f"core value {i}",
                    importance_score=0.8,
                    memory_layer="principle",
                    archived=False,
                    created_at=datetime.utcnow(),
                ))
            await s.commit()

        async with Session() as s:
            robot = await s.get(Robot, rid)
            result = await check_evolution(s, _FakeLLM(), robot)
            portrait = dict(robot.portrait or {})

        await engine.dispose()
        return result, portrait

    result, portrait = asyncio.run(scenario())
    assert result is True, f"Expected True (accepted), got {result}"
    # Portrait should have history entry with the old summary
    history = portrait.get("history", [])
    assert len(history) >= 1
    assert history[-1]["summary"] == "平静温和"
    # drift > 0.35 recorded
    assert portrait.get("last_drift", 0.0) > 0.35
