import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    Text,
    Uuid,
    false as sa_false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

if settings.is_sqlite:
    from app.db.models_sqlite import PortableJSON as JSONB_TYPE
    from app.db.models_sqlite import PortableArray, PortableVector

    def ArrayType(item_type):
        return PortableArray(item_type)

    def VectorType(dim):
        return PortableVector(dim)
else:
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import ARRAY
    from sqlalchemy.dialects.postgresql import JSONB

    JSONB_TYPE = JSONB

    def ArrayType(item_type):
        return ARRAY(item_type)

    def VectorType(dim):
        return Vector(dim)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    robots: Mapped[list["Robot"]] = relationship(back_populates="user")


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer)
    birth_place: Mapped[str | None] = mapped_column(Text)
    origin_story: Mapped[str | None] = mapped_column(Text)
    core_desire: Mapped[str | None] = mapped_column(Text)
    core_fear: Mapped[str | None] = mapped_column(Text)
    personality: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    speaking_style: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    voice_profile: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    current_emotion: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    current_status: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    # Energy system (0-100, web search costs 10, sleep recovers)
    energy: Mapped[float | None] = mapped_column(Float, default=100.0)
    # Complete portrait generated after all memories
    portrait: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    # Generation cost tracking
    generation_stats: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    relationships_snapshot: Mapped[list | None] = mapped_column(JSONB_TYPE)
    desktop_visible: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="robots")
    yearly_memories: Mapped[list["YearlyMemory"]] = relationship(back_populates="robot")


class AssetVersion(Base):
    __tablename__ = "asset_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("robots.id"))
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'image' | 'voice_config'
    asset_key: Mapped[str] = mapped_column(Text, nullable=False)  # state name or 'voice_profile'
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB_TYPE)
    is_current: Mapped[bool] = mapped_column(default=False)
    is_starred: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class YearlyMemory(Base):
    __tablename__ = "yearly_memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("robots.id"))
    age: Mapped[int] = mapped_column(Integer)
    memory_title: Mapped[str | None] = mapped_column(Text)
    memory_content: Mapped[str | None] = mapped_column(Text)
    memory_summary: Mapped[str | None] = mapped_column(Text)
    emotional_impact: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    personality_effect: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    memory_type: Mapped[str | None] = mapped_column(Text)  # vivid/fragment/feeling
    importance: Mapped[float | None] = mapped_column(Float, default=0.5)
    memory_strength: Mapped[float | None] = mapped_column(Float, default=1.0)
    symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
    word_count: Mapped[int | None] = mapped_column(Integer, default=0)
    generation_time_ms: Mapped[int | None] = mapped_column(Integer, default=0)
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)
    batch_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    robot: Mapped["Robot"] = relationship(back_populates="yearly_memories")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    owner_type: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    memory_type: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    importance_score: Mapped[float | None] = mapped_column(Float)
    emotional_valence: Mapped[float | None] = mapped_column(Float)
    emotional_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
    symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
    related_robot_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ArrayType(Uuid))
    related_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    embedding = mapped_column(VectorType(settings.embedding_dimensions), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    last_accessed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # Memory evolution fields
    base_importance: Mapped[float | None] = mapped_column(Float, default=0.5)
    last_activated: Mapped[datetime | None] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    activation_count: Mapped[int | None] = mapped_column(Integer, default=0)
    reinterpretation: Mapped[str | None] = mapped_column(Text)
    linked_memory_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ArrayType(Uuid))
    memory_source: Mapped[str | None] = mapped_column(Text, default="conversation")
    # --- Self-iteration (P1) ---
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    useful_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    utility_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    consolidated_into: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    memory_layer: Mapped[str] = mapped_column(Text, default="episodic", server_default="episodic")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("robots.id"))
    event_type: Mapped[str] = mapped_column(Text)  # thought/speak/chat/search/learn/evolve
    content: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB_TYPE)  # extra data (search results, changes, etc)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    relationship_type: Mapped[str | None] = mapped_column(Text)
    intimacy: Mapped[float] = mapped_column(Float, default=0.5)
    trust: Mapped[float] = mapped_column(Float, default=0.5)
    tension: Mapped[float] = mapped_column(Float, default=0.0)
    jealousy: Mapped[float] = mapped_column(Float, default=0.0)
    understanding: Mapped[float] = mapped_column(Float, default=0.3)
    history_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    conversation_type: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id")
    )
    sender_type: Mapped[str | None] = mapped_column(Text)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sender_name: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    emotion: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class RobotSkill(Base):
    __tablename__ = "robot_skills"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("robots.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)           # "写俳句"
    description: Mapped[str | None] = mapped_column(Text)             # why/what
    trigger_keywords: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
    execution_prompt: Mapped[str | None] = mapped_column(Text)        # how to execute
    skill_type: Mapped[str | None] = mapped_column(Text)              # creative/knowledge/social/search
    tool_name: Mapped[str | None] = mapped_column(Text)  # 非空表示这是注册表里的工具技能
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    acquired_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class ObjectObservation(Base):
    __tablename__ = "object_observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    object_name: Mapped[str | None] = mapped_column(Text)
    object_description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
    robot_reactions: Mapped[dict | None] = mapped_column(JSONB_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
