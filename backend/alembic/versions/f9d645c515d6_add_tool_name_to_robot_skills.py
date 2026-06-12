"""add tool_name to robot_skills

Revision ID: f9d645c515d6
Revises: 9346fcfb1039
Create Date: 2026-06-12 15:23:31.980519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9d645c515d6'
down_revision: Union[str, Sequence[str], None] = '9346fcfb1039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('robot_skills', sa.Column('tool_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('robot_skills', 'tool_name')
