import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Robot
from app.services.orchestrator import Orchestrator


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    # Director call
    llm.generate_structured = AsyncMock(
        return_value={
            "next_speaker": "Momo",
            "emotion_tone": "curious",
            "should_end": False,
            "director_note": "Momo should express wonder",
        }
    )
    # Speaker call
    llm.generate = AsyncMock(return_value="哇，这个杯子好有意思！")
    return llm


@pytest.fixture
def robots():
    user_id = uuid.uuid4()
    return [
        Robot(
            id=uuid.uuid4(),
            user_id=user_id,
            name="Momo",
            personality=["温柔"],
            origin_story="出生在钟表店",
            speaking_style={"speed": "slow", "sentence_length": "short"},
        ),
        Robot(
            id=uuid.uuid4(),
            user_id=user_id,
            name="Kiki",
            personality=["活泼"],
            origin_story="出生在花园",
            speaking_style={"speed": "fast", "sentence_length": "medium"},
        ),
    ]


@pytest.fixture
def service(mock_session, mock_llm):
    mock_memory = AsyncMock()
    mock_memory.search_memories = AsyncMock(return_value=[])
    mock_relationship = AsyncMock()
    mock_relationship.get_relationships_for_robot = AsyncMock(return_value=[])
    mock_relationship.update_from_conversation_summary = AsyncMock()
    return Orchestrator(
        session=mock_session,
        llm=mock_llm,
        memory_service=mock_memory,
        relationship_service=mock_relationship,
    )


@pytest.mark.asyncio
async def test_director_decides_next_speaker(service, mock_llm, robots):
    decision = await service.get_director_decision(
        topic="讨论红色杯子",
        robots=robots,
        relationships=[],
        conversation_so_far=[],
    )
    assert decision["next_speaker"] == "Momo"


@pytest.mark.asyncio
async def test_generate_speaker_message(service, mock_llm, robots):
    message = await service.generate_speaker_message(
        robot=robots[0],
        conversation_so_far=[],
        director_note="express wonder",
    )
    assert isinstance(message, str)
    assert len(message) > 0
