import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_session
from app.db.models import Robot
from app.schemas import ObjectObserveRequest, ObjectObserveResponse
from app.services.imagination import ImaginationService
from app.services.llm.factory import create_llm
from app.services.memory import MemoryService

router = APIRouter(prefix="/api/objects", tags=["objects"])

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/observe", response_model=ObjectObserveResponse)
async def observe_object(
    body: ObjectObserveRequest,
    session: AsyncSession = Depends(get_session),
):
    llm = create_llm(
        settings.llm_provider,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
    )
    memory_service = MemoryService(session=session, llm=llm)
    imagination_service = ImaginationService(
        session=session, llm=llm, memory_service=memory_service
    )

    # Get robots
    if body.robot_ids:
        stmt = select(Robot).where(Robot.id.in_(body.robot_ids))
    else:
        stmt = select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
    result = await session.execute(stmt)
    robots = list(result.scalars().all())

    if not robots:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="No robots found")

    observation = await imagination_service.observe_object(
        user_id=DEFAULT_USER_ID,
        robots=robots,
        text_description=body.text_description,
        image_url=body.image_url,
    )
    return observation
