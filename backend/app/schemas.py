import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --- Robot ---

class SpeakingStyle(BaseModel):
    speed: str = "medium"
    tone: str = "neutral"
    sentence_length: str = "medium"
    metaphor_level: str = "medium"


class VoiceProfile(BaseModel):
    gender_feeling: str = "neutral"
    age_feeling: str = "young"
    pitch: str = "medium"
    emotion_range: str = "warm"


class RobotCreate(BaseModel):
    count: int = Field(default=3, ge=1, le=5)
    preferences: str | None = None



class YearlyMemoryOut(BaseModel):
    id: uuid.UUID
    age: int
    memory_title: str | None
    memory_content: str | None
    emotional_impact: dict | None
    importance: float | None
    memory_strength: float | None
    symbolic_tags: list[str] | None

    model_config = {"from_attributes": True}


class RobotOut(BaseModel):
    id: uuid.UUID
    name: str
    age: int | None
    birth_place: str | None
    origin_story: str | None
    core_desire: str | None
    core_fear: str | None
    personality: list | dict | None
    speaking_style: dict | None
    voice_profile: dict | None
    current_emotion: dict | None
    current_status: str | None
    energy: float | None
    generation_stats: dict | None
    relationships_snapshot: list | None = None
    desktop_visible: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class RobotDetail(RobotOut):
    yearly_memories: list[YearlyMemoryOut] = []
    portrait: dict | None = None


# --- Object Observation ---

class RobotReaction(BaseModel):
    robot_id: uuid.UUID
    robot_name: str
    inner_thought: str
    user_expression: str
    should_remember: bool
    emotion_change: dict | None


class ObjectObserveRequest(BaseModel):
    text_description: str | None = None
    image_url: str | None = None
    robot_ids: list[uuid.UUID] | None = None


class ObjectObserveResponse(BaseModel):
    id: uuid.UUID
    object_name: str | None
    object_description: str | None
    symbolic_tags: list[str] | None
    reactions: list[RobotReaction]


# --- Conversation / Chat ---

class MessageOut(BaseModel):
    id: uuid.UUID
    sender_type: str | None
    sender_id: uuid.UUID | None
    sender_name: str | None
    content: str | None
    emotion: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: uuid.UUID
    conversation_type: str | None
    topic: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserMessageRequest(BaseModel):
    content: str


# --- Agents ---

class IdleChatRequest(BaseModel):
    topic: str | None = None
    robot_ids: list[uuid.UUID] | None = None


class IdleChatResponse(BaseModel):
    conversation_id: uuid.UUID
    stream_url: str
