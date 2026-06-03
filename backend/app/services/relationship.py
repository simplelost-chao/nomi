import uuid
from itertools import combinations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Relationship


class RelationshipService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_initial_relationships(
        self,
        user_id: uuid.UUID,
        robot_ids: list[uuid.UUID],
    ) -> list[Relationship]:
        relationships = []
        for a, b in combinations(robot_ids, 2):
            rel = Relationship(
                user_id=user_id,
                subject_type="robot",
                subject_id=a,
                object_type="robot",
                object_id=b,
                relationship_type="companion",
                intimacy=0.5,
                trust=0.5,
                tension=0.0,
                jealousy=0.0,
                understanding=0.3,
            )
            relationships.append(rel)
        self.session.add_all(relationships)
        await self.session.commit()
        return relationships

    async def get_relationships_for_robot(
        self,
        robot_id: uuid.UUID,
    ) -> list[Relationship]:
        stmt = select(Relationship).where(
            (Relationship.subject_id == robot_id)
            | (Relationship.object_id == robot_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_relationship_between(
        self,
        robot_a: uuid.UUID,
        robot_b: uuid.UUID,
    ) -> Relationship | None:
        stmt = select(Relationship).where(
            ((Relationship.subject_id == robot_a) & (Relationship.object_id == robot_b))
            | ((Relationship.subject_id == robot_b) & (Relationship.object_id == robot_a))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def apply_deltas(
        self,
        rel: Relationship,
        intimacy_delta: float = 0.0,
        trust_delta: float = 0.0,
        tension_delta: float = 0.0,
    ) -> None:
        rel.intimacy = max(0.0, min(1.0, rel.intimacy + intimacy_delta))
        rel.trust = max(0.0, min(1.0, rel.trust + trust_delta))
        rel.tension = max(0.0, min(1.0, rel.tension + tension_delta))

    async def update_from_conversation_summary(
        self,
        changes: list[dict],
        robot_name_to_id: dict[str, uuid.UUID],
    ) -> None:
        for change in changes:
            a_id = robot_name_to_id.get(change["robot_a"])
            b_id = robot_name_to_id.get(change["robot_b"])
            if not a_id or not b_id:
                continue
            rel = await self.get_relationship_between(a_id, b_id)
            if not rel:
                continue
            self.apply_deltas(
                rel,
                intimacy_delta=change.get("intimacy_delta", 0.0),
                trust_delta=change.get("trust_delta", 0.0),
                tension_delta=change.get("tension_delta", 0.0),
            )
            if change.get("reason"):
                existing = rel.history_summary or ""
                rel.history_summary = f"{existing}\n{change['reason']}".strip()
        await self.session.commit()
