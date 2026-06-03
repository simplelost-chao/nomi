import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory import MemoryService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture
def memory_service(mock_session, mock_llm):
    return MemoryService(session=mock_session, llm=mock_llm)


@pytest.mark.asyncio
async def test_write_memory_calls_embed(memory_service, mock_llm):
    user_id = uuid.uuid4()
    robot_id = uuid.uuid4()
    await memory_service.write_memory(
        user_id=user_id,
        owner_type="robot",
        owner_id=robot_id,
        memory_type="observation",
        content="I saw a red cup today",
        importance_score=0.7,
    )
    mock_llm.embed.assert_called_once_with("I saw a red cup today")


@pytest.mark.asyncio
async def test_write_memory_adds_to_session(memory_service, mock_session):
    user_id = uuid.uuid4()
    robot_id = uuid.uuid4()
    await memory_service.write_memory(
        user_id=user_id,
        owner_type="robot",
        owner_id=robot_id,
        memory_type="observation",
        content="I saw a red cup today",
        importance_score=0.7,
    )
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
