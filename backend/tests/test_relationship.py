import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.relationship import RelationshipService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def service(mock_session):
    return RelationshipService(session=mock_session)


@pytest.mark.asyncio
async def test_create_initial_relationships(service, mock_session):
    user_id = uuid.uuid4()
    robot_ids = [uuid.uuid4() for _ in range(3)]
    await service.create_initial_relationships(user_id, robot_ids)
    # 3 robots = 3 pairs (A-B, A-C, B-C)
    mock_session.add_all.assert_called_once()
    relationships = mock_session.add_all.call_args[0][0]
    assert len(relationships) == 3


@pytest.mark.asyncio
async def test_update_relationship_clamps_values(service):
    from app.db.models import Relationship

    rel = Relationship(intimacy=0.9, trust=0.1, tension=0.0)
    service.apply_deltas(rel, intimacy_delta=0.5, trust_delta=-0.5, tension_delta=-0.1)
    assert rel.intimacy == 1.0  # clamped
    assert rel.trust == 0.0  # clamped
    assert rel.tension == 0.0  # clamped at 0
