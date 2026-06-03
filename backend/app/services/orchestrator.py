import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, Robot
from app.prompts.director import (
    build_conversation_summary_prompt,
    build_director_prompt,
    build_speaker_prompt,
)
from app.services.llm.base import BaseLLM
from app.services.memory import MemoryService
from app.services.relationship import RelationshipService


class Orchestrator:
    def __init__(
        self,
        session: AsyncSession,
        llm: BaseLLM,
        memory_service: MemoryService,
        relationship_service: RelationshipService,
    ):
        self.session = session
        self.llm = llm
        self.memory_service = memory_service
        self.relationship_service = relationship_service

    async def get_director_decision(
        self,
        topic: str,
        robots: list[Robot],
        relationships: list[dict],
        conversation_so_far: list[dict],
    ) -> dict:
        system, user_msg = build_director_prompt(
            topic=topic,
            robots=[
                {"name": r.name, "personality": r.personality or []}
                for r in robots
            ],
            relationships=relationships,
            conversation_so_far=conversation_so_far,
        )
        return await self.llm.generate_structured(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

    async def generate_speaker_message(
        self,
        robot: Robot,
        conversation_so_far: list[dict],
        director_note: str,
    ) -> str:
        # Retrieve memories related to the conversation topic
        topic_text = " ".join(m.get("content", "") for m in conversation_so_far[-3:])
        memories = []
        if topic_text.strip():
            mems = await self.memory_service.search_memories(
                query=topic_text,
                user_id=robot.user_id,
                owner_id=robot.id,
                limit=3,
            )
            memories = [m.content for m in mems if m.content]

        # Get relationships
        rels = await self.relationship_service.get_relationships_for_robot(robot.id)
        rel_dicts = [
            {"with": "other", "intimacy": r.intimacy}
            for r in rels
        ]

        system, user_msg = build_speaker_prompt(
            robot_name=robot.name,
            robot_personality=robot.personality or [],
            origin_story=robot.origin_story or "",
            speaking_style=robot.speaking_style or {},
            memories=memories,
            relationships=rel_dicts,
            conversation_so_far=conversation_so_far,
            director_note=director_note,
        )
        return await self.llm.generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=system,
        )

    async def run_idle_chat(
        self,
        user_id: uuid.UUID,
        robots: list[Robot],
        topic: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Runs an autonomous chat session, yielding SSE events."""

        # Create conversation record
        conversation = Conversation(
            user_id=user_id,
            conversation_type="idle_chat",
            topic=topic or "自由聊天",
        )
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)

        robot_map = {r.name: r for r in robots}
        conversation_so_far: list[dict] = []
        relationships: list[dict] = []

        max_rounds = 10
        for round_num in range(max_rounds):
            # Director decides
            decision = await self.get_director_decision(
                topic=topic or "自由聊天",
                robots=robots,
                relationships=relationships,
                conversation_so_far=conversation_so_far,
            )

            if decision.get("should_end", False) and round_num >= 7:
                break

            speaker_name = decision.get("next_speaker", robots[round_num % len(robots)].name)
            speaker = robot_map.get(speaker_name, robots[round_num % len(robots)])

            # Yield typing event
            yield {
                "event": "typing",
                "data": json.dumps({"robot_name": speaker.name}),
            }

            # Generate message
            content = await self.generate_speaker_message(
                robot=speaker,
                conversation_so_far=conversation_so_far,
                director_note=decision.get("director_note", ""),
            )

            # Save message
            message = Message(
                conversation_id=conversation.id,
                sender_type="robot",
                sender_id=speaker.id,
                sender_name=speaker.name,
                content=content,
                emotion={"tone": decision.get("emotion_tone", "neutral")},
            )
            self.session.add(message)
            await self.session.commit()

            conversation_so_far.append({
                "sender": speaker.name,
                "content": content,
            })

            # Yield message event
            yield {
                "event": "message",
                "data": json.dumps({
                    "id": str(message.id),
                    "sender_name": speaker.name,
                    "sender_id": str(speaker.id),
                    "content": content,
                    "emotion": message.emotion,
                    "created_at": message.created_at.isoformat(),
                }, ensure_ascii=False),
            }

            await asyncio.sleep(0.5)  # Small delay for natural feel

        # Generate summary
        summary_system, summary_msg = build_conversation_summary_prompt(
            robots=[
                {"name": r.name, "personality": r.personality or []}
                for r in robots
            ],
            conversation=conversation_so_far,
        )
        summary = await self.llm.generate_structured(
            messages=[{"role": "user", "content": summary_msg}],
            system_prompt=summary_system,
        )

        # Write shared memory
        shared_mem = summary.get("shared_memory", {})
        if shared_mem:
            await self.memory_service.write_memory(
                user_id=user_id,
                owner_type="shared",
                owner_id=conversation.id,
                memory_type="relationship",
                content=shared_mem.get("content", ""),
                importance_score=shared_mem.get("importance_score", 0.5),
                emotional_tags=shared_mem.get("emotional_tags", []),
                symbolic_tags=shared_mem.get("symbolic_tags", []),
                related_robot_ids=[r.id for r in robots],
            )

        # Write personal memories
        for pm in summary.get("personal_memories", []):
            robot = robot_map.get(pm.get("robot_name"))
            if robot:
                await self.memory_service.write_memory(
                    user_id=user_id,
                    owner_type="robot",
                    owner_id=robot.id,
                    memory_type="relationship",
                    content=pm.get("content", ""),
                    importance_score=pm.get("importance_score", 0.5),
                )

        # Update relationships
        robot_name_to_id = {r.name: r.id for r in robots}
        await self.relationship_service.update_from_conversation_summary(
            changes=summary.get("relationship_changes", []),
            robot_name_to_id=robot_name_to_id,
        )

        # Update conversation summary
        conversation.summary = shared_mem.get("content", "")
        await self.session.commit()

        # Yield end event
        yield {
            "event": "chat_end",
            "data": json.dumps({
                "conversation_id": str(conversation.id),
                "summary": shared_mem.get("content", ""),
            }, ensure_ascii=False),
        }
