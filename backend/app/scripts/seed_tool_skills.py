"""Seed built-in tool skills for all robots (idempotent).

Run from backend/: python -m app.scripts.seed_tool_skills
"""

import asyncio

from sqlalchemy import select

import app.services.tools  # noqa: F401 — import side-effect registers tools
from app.db.engine import async_session
from app.db.models import Robot, RobotSkill
from app.services.tools.registry import all_tools


async def seed_tool_skills(session, robot_id) -> int:
    """Insert missing tool skills for one robot. Returns number added."""
    existing = set((await session.execute(
        select(RobotSkill.tool_name)
        .where(RobotSkill.robot_id == robot_id)
        .where(RobotSkill.tool_name.isnot(None))
    )).scalars().all())

    added = 0
    for tool in all_tools():
        if tool.name in existing:
            continue
        session.add(RobotSkill(
            robot_id=robot_id,
            name=tool.display_name,
            description=tool.description,
            trigger_keywords=tool.trigger_hints,
            execution_prompt=None,
            skill_type="tool",
            tool_name=tool.name,
            usage_count=0,
        ))
        added += 1
    await session.commit()
    return added


async def main():
    async with async_session() as session:
        robots = (await session.execute(select(Robot))).scalars().all()
        for robot in robots:
            n = await seed_tool_skills(session, robot.id)
            print(f"{robot.name}: +{n} tool skills")


if __name__ == "__main__":
    asyncio.run(main())
