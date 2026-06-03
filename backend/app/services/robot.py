import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Robot, User, YearlyMemory
from app.prompts.creation import (
    build_life_memories_prompt,
    build_robot_creation_from_image_prompt,
    build_robot_creation_prompt,
    build_yearly_memories_prompt,
)
from app.services.llm.base import BaseLLM
from app.services.relationship import RelationshipService


class RobotService:
    def __init__(self, session: AsyncSession, llm: BaseLLM):
        self.session = session
        self.llm = llm

    async def create_robot_from_object(
        self,
        user_id: uuid.UUID,
        object_description: str,
        existing_robots: list[dict] | None = None,
    ) -> Robot:
        """Create a single robot based on an object description."""
        # Ensure user exists
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=user_id)
            self.session.add(user)
            await self.session.commit()

        # Generate profile from object
        system, user_msg = build_robot_creation_from_image_prompt(
            object_description=object_description,
            existing_robots=existing_robots or [],
        )
        profile = await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

        robot = Robot(
            user_id=user_id,
            name=profile["name"],
            age=profile.get("age", 5),
            birth_place=profile.get("birth_place"),
            origin_story=profile.get("origin_story"),
            core_desire=profile.get("core_desire"),
            core_fear=profile.get("core_fear"),
            personality=profile.get("core_personality"),
            speaking_style=profile.get("speaking_style"),
            voice_profile=profile.get("voice_profile"),
            current_emotion={"emotion": "calm", "intensity": 0.3},
            current_status="just_born",
        )
        self.session.add(robot)
        await self.session.commit()
        await self.session.refresh(robot)

        # Generate life memories with decay
        system, user_msg = build_life_memories_prompt(
            robot_name=robot.name,
            robot_age=robot.age,
            origin_story=robot.origin_story or "",
            personality=robot.personality or [],
            object_description=object_description,
        )
        memories_data = await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

        if isinstance(memories_data, list):
            for mem in memories_data:
                yearly_mem = YearlyMemory(
                    robot_id=robot.id,
                    age=mem.get("age", 0),
                    memory_title=mem.get("memory_title"),
                    memory_content=mem.get("memory_content"),
                    emotional_impact=mem.get("emotional_impact"),
                    importance=mem.get("importance", 0.5),
                    memory_strength=mem.get("memory_strength", 0.5),
                    symbolic_tags=mem.get("symbolic_tags", []),
                )
                self.session.add(yearly_mem)

        await self.session.commit()
        return robot

    async def generate_robot_profile(
        self,
        existing_robots: list[dict],
        preferences: str | None = None,
    ) -> dict:
        system, user_msg = build_robot_creation_prompt(
            existing_robots=existing_robots,
            preferences=preferences,
        )
        return await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

    async def generate_yearly_memories(
        self,
        robot_name: str,
        robot_age: int,
        origin_story: str,
        personality: list[str],
    ) -> list[dict]:
        system, user_msg = build_yearly_memories_prompt(
            robot_name=robot_name,
            robot_age=robot_age,
            origin_story=origin_story,
            personality=personality,
        )
        return await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

    async def create_robots(
        self,
        user_id: uuid.UUID,
        count: int = 3,
        preferences: str | None = None,
    ) -> list[Robot]:
        # Ensure user exists
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=user_id)
            self.session.add(user)
            await self.session.commit()

        robots = []
        existing_summaries = []

        for i in range(count):
            profile = await self.generate_robot_profile(
                existing_robots=existing_summaries,
                preferences=preferences,
            )

            robot = Robot(
                user_id=user_id,
                name=profile["name"],
                age=profile.get("age", 5),
                birth_place=profile.get("birth_place"),
                origin_story=profile.get("origin_story"),
                core_desire=profile.get("core_desire"),
                core_fear=profile.get("core_fear"),
                personality=profile.get("core_personality"),
                speaking_style=profile.get("speaking_style"),
                voice_profile=profile.get("voice_profile"),
                current_emotion={"emotion": "calm", "intensity": 0.3},
                current_status="just_born",
            )
            self.session.add(robot)
            await self.session.commit()
            await self.session.refresh(robot)

            memories_data = await self.generate_yearly_memories(
                robot_name=robot.name,
                robot_age=robot.age,
                origin_story=robot.origin_story or "",
                personality=robot.personality or [],
            )

            if isinstance(memories_data, list):
                for mem in memories_data:
                    yearly_mem = YearlyMemory(
                        robot_id=robot.id,
                        age=mem.get("age", 0),
                        memory_title=mem.get("memory_title"),
                        memory_content=mem.get("memory_content"),
                        emotional_impact=mem.get("emotional_impact"),
                        importance=mem.get("importance", 0.5),
                        memory_strength=mem.get("memory_strength", 0.5),
                        symbolic_tags=mem.get("symbolic_tags", []),
                    )
                    self.session.add(yearly_mem)

            await self.session.commit()
            robots.append(robot)
            existing_summaries.append({
                "name": robot.name,
                "personality": robot.personality,
            })

        if len(robots) > 1:
            rel_service = RelationshipService(self.session)
            await rel_service.create_initial_relationships(
                user_id=user_id,
                robot_ids=[r.id for r in robots],
            )

        return robots

    async def get_robots(self, user_id: uuid.UUID) -> list[Robot]:
        stmt = select(Robot).where(Robot.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_robot_detail(self, robot_id: uuid.UUID) -> Robot | None:
        stmt = (
            select(Robot)
            .where(Robot.id == robot_id)
            .options(selectinload(Robot.yearly_memories))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
