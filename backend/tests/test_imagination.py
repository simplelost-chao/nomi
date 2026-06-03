import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.imagination import ImaginationService


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
    llm.generate_structured = AsyncMock(
        side_effect=[
            # First call: object description
            {
                "object_name": "红色杯子",
                "object_description": "一个红色的陶瓷杯子，表面有细小的裂纹",
                "symbolic_tags": ["温暖", "日常", "时间"],
            },
            # Second call: robot reaction
            {
                "inner_thought": "这个杯子让我想起了钟表店里的茶杯",
                "user_expression": "主人，这个杯子上的裂纹好像在讲故事呢...",
                "should_remember": True,
                "memory_content": "看到一个有裂纹的红色杯子，想起了钟表店",
                "emotion_change": {"emotion": "nostalgic", "intensity": 0.6},
            },
        ]
    )
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture
def mock_memory_service():
    service = AsyncMock()
    service.search_memories = AsyncMock(return_value=[])
    service.write_memory = AsyncMock()
    return service


@pytest.fixture
def service(mock_session, mock_llm, mock_memory_service):
    return ImaginationService(
        session=mock_session, llm=mock_llm, memory_service=mock_memory_service
    )


@pytest.mark.asyncio
async def test_describe_object(service, mock_llm):
    result = await service.describe_object(text_description="一个红色杯子")
    assert result["object_name"] == "红色杯子"


@pytest.mark.asyncio
async def test_generate_reaction(service, mock_llm, mock_memory_service):
    from app.db.models import Robot

    robot = Robot(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Momo",
        personality=["温柔"],
        origin_story="出生在钟表店",
        speaking_style={"speed": "slow"},
    )
    # Skip the first call (object description), go straight to reaction
    mock_llm.generate_structured = AsyncMock(
        return_value={
            "inner_thought": "这个杯子让我想起了钟表店里的茶杯",
            "user_expression": "主人，这个杯子上的裂纹好像在讲故事呢...",
            "should_remember": True,
            "memory_content": "看到一个有裂纹的红色杯子，想起了钟表店",
            "emotion_change": {"emotion": "nostalgic", "intensity": 0.6},
        }
    )
    reaction = await service.generate_reaction(
        robot=robot,
        object_description="一个红色的陶瓷杯子",
    )
    assert reaction["robot_name"] == "Momo"
    assert reaction["should_remember"] is True
    mock_memory_service.write_memory.assert_called_once()
