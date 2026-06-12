"""add reminders and tool_settings tables

Revision ID: ad0e84c74b4c
Revises: d62a3d30fc76
Create Date: 2026-06-12 16:50:51.931994

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad0e84c74b4c'
down_revision: Union[str, Sequence[str], None] = 'd62a3d30fc76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("robot_id", sa.Uuid(), sa.ForeignKey("robots.id"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("trigger_time", sa.TIMESTAMP(), nullable=False),
        sa.Column("repeat", sa.Text(), nullable=False, server_default="once"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "tool_settings",
        sa.Column("tool_name", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("tool_settings")
    op.drop_table("reminders")
