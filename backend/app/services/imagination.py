import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObjectObservation, Robot
from app.prompts.imagination import (
    build_imagination_prompt,
    build_object_description_prompt,
)
from app.services.llm.base import BaseLLM
from app.services.memory import MemoryService


class ImaginationService:
    def __init__(
        self, session: AsyncSession, llm: BaseLLM, memory_service: MemoryService
    ):
        self.session = session
        self.llm = llm
        self.memory_service = memory_service

    async def describe_object(
        self,
        text_description: str | None = None,
        image_url: str | None = None,
    ) -> dict:
        system, user_msg = build_object_description_prompt(
            text_description=text_description,
            image_url=image_url,
        )
        return await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

    async def generate_reaction(
        self,
        robot: Robot,
        object_description: str,
    ) -> dict:
        # Search for related memories
        memories = await self.memory_service.search_memories(
            query=object_description,
            user_id=robot.user_id,
            owner_id=robot.id,
            limit=3,
        )
        memory_texts = [m.content for m in memories if m.content]

        personality = robot.personality or []
        if isinstance(personality, dict):
            personality = list(personality.values()) if personality else []

        system, user_msg = build_imagination_prompt(
            robot_name=robot.name,
            robot_personality=personality,
            origin_story=robot.origin_story or "",
            speaking_style=robot.speaking_style or {},
            memories=memory_texts,
            object_description=object_description,
        )

        reaction = await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

        # Write memory if should_remember
        if reaction.get("should_remember"):
            memory_content = reaction.get("memory_content", object_description)
            await self.memory_service.write_memory(
                user_id=robot.user_id,
                owner_type="robot",
                owner_id=robot.id,
                memory_type="observation",
                content=memory_content,
                importance_score=0.6,
                emotional_tags=[reaction.get("emotion_change", {}).get("emotion", "")],
                symbolic_tags=[],
            )

        # Update robot emotion
        if reaction.get("emotion_change"):
            robot.current_emotion = reaction["emotion_change"]

        return {
            "robot_id": robot.id,
            "robot_name": robot.name,
            "inner_thought": reaction.get("inner_thought", ""),
            "user_expression": reaction.get("user_expression", ""),
            "should_remember": reaction.get("should_remember", False),
            "emotion_change": reaction.get("emotion_change"),
        }

    async def observe_object(
        self,
        user_id: uuid.UUID,
        robots: list[Robot],
        text_description: str | None = None,
        image_url: str | None = None,
    ) -> dict:
        # Step 1: Generate objective description
        obj_desc = await self.describe_object(
            text_description=text_description,
            image_url=image_url,
        )

        # Step 2: Each robot reacts
        reactions = []
        for robot in robots:
            reaction = await self.generate_reaction(
                robot=robot,
                object_description=obj_desc.get("object_description", text_description or ""),
            )
            reactions.append(reaction)

        # Step 3: Save observation record
        observation = ObjectObservation(
            user_id=user_id,
            object_name=obj_desc.get("object_name"),
            object_description=obj_desc.get("object_description"),
            image_url=image_url,
            symbolic_tags=obj_desc.get("symbolic_tags", []),
            robot_reactions={r["robot_name"]: r for r in reactions},
        )
        self.session.add(observation)
        await self.session.commit()
        await self.session.refresh(observation)

        return {
            "id": observation.id,
            "object_name": observation.object_name,
            "object_description": observation.object_description,
            "symbolic_tags": observation.symbolic_tags,
            "reactions": reactions,
        }
