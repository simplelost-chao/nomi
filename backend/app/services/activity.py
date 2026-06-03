"""Activity logging — records all robot behaviors for display."""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog


async def log_activity(
    session: AsyncSession,
    robot_id: uuid.UUID,
    event_type: str,
    content: str,
    detail: dict | None = None,
):
    """Log a robot activity event.

    event_type:
    - thought: inner thought
    - speak: said something
    - chat: conversation with another robot
    - search: web search triggered
    - learn: learned something new
    - evolve: personality/portrait changed
    - reflect: self-reflection
    """
    log = ActivityLog(
        robot_id=robot_id,
        event_type=event_type,
        content=content,
        detail=detail,
    )
    session.add(log)
    await session.commit()
