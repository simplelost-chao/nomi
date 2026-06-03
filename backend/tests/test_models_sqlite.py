import os
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="SQLite tests require NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db",
)


@pytest.fixture
def sqlite_engine(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    from app.db.models import Base
    Base.metadata.create_all(engine)
    return engine


def test_all_tables_created(sqlite_engine):
    inspector = inspect(sqlite_engine)
    table_names = inspector.get_table_names()
    expected = [
        "users", "robots", "yearly_memories", "memories",
        "activity_logs", "relationships", "conversations",
        "messages", "robot_skills", "object_observations",
    ]
    for table in expected:
        assert table in table_names, f"Table {table} not created"


def test_insert_and_read_robot(sqlite_engine):
    import uuid
    from app.db.models import User, Robot

    with Session(sqlite_engine) as session:
        user = User(id=uuid.uuid4(), name="test")
        session.add(user)
        session.flush()

        robot = Robot(
            id=uuid.uuid4(),
            user_id=user.id,
            name="TestBot",
            personality={"trait": "friendly"},
            speaking_style={"tone": "warm"},
        )
        session.add(robot)
        session.commit()

        fetched = session.get(Robot, robot.id)
        assert fetched.name == "TestBot"
        assert fetched.personality == {"trait": "friendly"}


def test_insert_and_read_memory_with_array(sqlite_engine):
    import uuid
    from app.db.models import User, Memory

    with Session(sqlite_engine) as session:
        user = User(id=uuid.uuid4(), name="test")
        session.add(user)
        session.flush()

        memory = Memory(
            id=uuid.uuid4(),
            user_id=user.id,
            owner_type="robot",
            owner_id=uuid.uuid4(),
            memory_type="episodic",
            content="test memory",
            emotional_tags=["happy", "excited"],
            symbolic_tags=["friendship"],
        )
        session.add(memory)
        session.commit()

        fetched = session.get(Memory, memory.id)
        assert fetched.emotional_tags == ["happy", "excited"]
        assert fetched.symbolic_tags == ["friendship"]


def test_memory_iteration_fields_exist(sqlite_engine):
    import uuid
    from sqlalchemy.orm import Session
    from app.db.models import User, Memory

    with Session(sqlite_engine) as session:
        user = User(id=uuid.uuid4(), name="t")
        session.add(user)
        session.flush()
        m = Memory(id=uuid.uuid4(), user_id=user.id, content="hi")
        session.add(m)
        session.commit()
        fetched = session.get(Memory, m.id)
        assert fetched.retrieved_count == 0
        assert fetched.useful_count == 0
        assert fetched.utility_score == 0.0
        assert fetched.consolidated_into is None
        assert fetched.archived is False


def test_memory_layer_defaults_episodic(sqlite_engine):
    import uuid
    from sqlalchemy.orm import Session
    from app.db.models import User, Memory
    with Session(sqlite_engine) as s:
        u = User(id=uuid.uuid4(), name="t"); s.add(u); s.flush()
        m = Memory(id=uuid.uuid4(), user_id=u.id, content="x"); s.add(m); s.commit()
        assert s.get(Memory, m.id).memory_layer == "episodic"
