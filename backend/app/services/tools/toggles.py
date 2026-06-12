"""DB-backed tool enable/disable, hydrated into the in-memory registry."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolSetting
from app.services.tools import registry


async def hydrate_tool_settings() -> None:
    """Load disabled set from DB into registry. Call once at app startup."""
    from app.db.engine import async_session
    try:
        async with async_session() as session:
            rows = (await session.execute(
                select(ToolSetting.tool_name).where(ToolSetting.enabled.is_(False))
            )).scalars().all()
            registry.set_disabled(set(rows))
            if rows:
                print(f"[tools] Disabled tools loaded: {sorted(rows)}")
    except Exception as e:
        print(f"[tools] Hydrate tool settings failed (non-fatal): {e}")


async def set_tool_enabled(session: AsyncSession, tool_name: str, enabled: bool) -> None:
    """Upsert DB row and update in-memory state."""
    row = (await session.execute(
        select(ToolSetting).where(ToolSetting.tool_name == tool_name)
    )).scalar_one_or_none()
    if row:
        row.enabled = enabled
        row.updated_at = datetime.utcnow()
    else:
        session.add(ToolSetting(tool_name=tool_name, enabled=enabled))
    await session.commit()
    registry.set_tool_state(tool_name, enabled)
