import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.robot import RobotService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate_structured = AsyncMock(
        return_value={
            "name": "Momo",
            "age": 8,
            "birth_place": "旧钟表店的抽屉",
            "origin_story": "Momo 出生在一个总是滴答作响的旧钟表店里。",
            "core_personality": ["温柔", "敏感", "怀旧"],
            "core_desire": "希望被某个人长期记住",
            "core_fear": "害怕被遗忘",
            "speaking_style": {
                "speed": "slow",
                "tone": "soft",
                "sentence_length": "short",
                "metaphor_level": "high",
            },
            "voice_profile": {
                "gender_feeling": "neutral-female",
                "age_feeling": "young",
                "pitch": "soft",
                "emotion_range": "warm",
            },
        }
    )
    return llm


@pytest.fixture
def service(mock_session, mock_llm):
    return RobotService(session=mock_session, llm=mock_llm)


@pytest.mark.asyncio
async def test_generate_robot_profile(service, mock_llm):
    profile = await service.generate_robot_profile(existing_robots=[])
    assert profile["name"] == "Momo"
    mock_llm.generate_structured.assert_called_once()


@pytest.mark.asyncio
async def test_generate_robot_profile_passes_existing(service, mock_llm):
    existing = [{"name": "Kiki", "personality": ["活泼"]}]
    await service.generate_robot_profile(existing_robots=existing)
    call_args = mock_llm.generate_structured.call_args
    # The system prompt should mention Kiki
    messages = call_args[1].get("messages") or call_args[0][0]
    system = call_args[1].get("system_prompt", "")
    assert "Kiki" in system
