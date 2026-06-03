import uuid
from datetime import datetime

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Memory
from app.services.llm.base import BaseLLM


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors using numpy."""
    a_arr = np.asarray(a, dtype=np.float64)
    b_arr = np.asarray(b, dtype=np.float64)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


class MemoryService:
    def __init__(self, session: AsyncSession, llm: BaseLLM):
        self.session = session
        self.llm = llm

    async def write_memory(
        self,
        user_id: uuid.UUID,
        owner_type: str,
        owner_id: uuid.UUID,
        memory_type: str,
        content: str,
        importance_score: float = 0.5,
        emotional_valence: float = 0.0,
        emotional_tags: list[str] | None = None,
        symbolic_tags: list[str] | None = None,
        related_robot_ids: list[uuid.UUID] | None = None,
        summary: str | None = None,
        memory_layer: str = "episodic",
    ) -> Memory:
        embedding = await self.llm.embed(content)

        memory = Memory(
            user_id=user_id,
            owner_type=owner_type,
            owner_id=owner_id,
            memory_type=memory_type,
            content=content,
            summary=summary or content[:100],
            importance_score=importance_score,
            emotional_valence=emotional_valence,
            emotional_tags=emotional_tags or [],
            symbolic_tags=symbolic_tags or [],
            related_robot_ids=related_robot_ids or [],
            embedding=embedding,
            memory_layer=memory_layer,
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def search_memories(
        self,
        query: str,
        user_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        limit: int = 3,
    ) -> list[Memory]:
        if settings.is_sqlite:
            return await self._search_memories_sqlite(query, user_id, owner_id, limit)

        from app.services.memory_iteration import rerank_candidates

        query_embedding = await self.llm.embed(query)
        candidate_k = max(limit * 5, 20)
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
            .where(Memory.archived.is_(False))
        )
        if owner_id:
            stmt = stmt.where(Memory.owner_id == owner_id)
        stmt = stmt.order_by(Memory.embedding.cosine_distance(query_embedding)).limit(candidate_k)

        result = await self.session.execute(stmt)
        candidates = list(result.scalars().all())
        memories = rerank_candidates(candidates, query_embedding, datetime.utcnow(), limit)

        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()
        return memories

    async def _search_memories_sqlite(
        self,
        query: str,
        user_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        limit: int = 3,
    ) -> list[Memory]:
        """Vector search fallback for SQLite: compute cosine similarity in Python."""
        query_embedding = await self.llm.embed(query)

        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
            .where(Memory.archived.is_(False))
        )
        if owner_id:
            stmt = stmt.where(Memory.owner_id == owner_id)

        result = await self.session.execute(stmt)
        all_memories = [m for m in result.scalars().all() if m.embedding is not None]
        from app.services.memory_iteration import rerank_candidates
        memories = rerank_candidates(all_memories, query_embedding, datetime.utcnow(), limit)
        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()

        return memories

    async def search_memories_layered(
        self,
        query: str,
        user_id: uuid.UUID,
        owner_id: uuid.UUID,
        budget: dict | None = None,
    ) -> list[Memory]:
        """Retrieve memories per layer using a per-layer budget dict."""
        from app.services.memory_iteration import allocate_layer_budget
        budget = budget or allocate_layer_budget()
        out: list[Memory] = []
        for layer, k in budget.items():
            if k <= 0:
                continue
            out.extend(await self._search_layer(query, user_id, owner_id, layer, k))
        return out

    async def _search_layer(
        self,
        query: str,
        user_id: uuid.UUID,
        owner_id: uuid.UUID | None,
        layer: str,
        k: int,
    ) -> list[Memory]:
        """Retrieve up to k memories from a single memory_layer, reranked."""
        from app.services.memory_iteration import rerank_candidates

        query_embedding = await self.llm.embed(query)

        if settings.is_sqlite:
            # SQLite path: fetch all matching candidates in Python, then rerank
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .where(Memory.embedding.isnot(None))
                .where(Memory.archived.is_(False))
                .where(Memory.memory_layer == layer)
            )
            if owner_id:
                stmt = stmt.where(Memory.owner_id == owner_id)
            result = await self.session.execute(stmt)
            candidates = [m for m in result.scalars().all() if m.embedding is not None]
        else:
            # Postgres path: use vector cosine_distance index for candidate pre-filter
            candidate_k = max(k * 5, 20)
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .where(Memory.embedding.isnot(None))
                .where(Memory.archived.is_(False))
                .where(Memory.memory_layer == layer)
            )
            if owner_id:
                stmt = stmt.where(Memory.owner_id == owner_id)
            stmt = stmt.order_by(Memory.embedding.cosine_distance(query_embedding)).limit(candidate_k)
            result = await self.session.execute(stmt)
            candidates = list(result.scalars().all())

        memories = rerank_candidates(candidates, query_embedding, datetime.utcnow(), k)
        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()
        return memories
