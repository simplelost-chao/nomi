from app.db.models import (
    Base,
    Conversation,
    Memory,
    Message,
    ObjectObservation,
    Relationship,
    Robot,
    User,
    YearlyMemory,
)


def test_all_models_registered():
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "robots",
        "yearly_memories",
        "memories",
        "relationships",
        "conversations",
        "messages",
        "object_observations",
        "robot_skills",
        "activity_logs",
        "asset_versions",
    }
    assert expected == table_names
