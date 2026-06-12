"""merge memory-layer and tool-skills heads

Revision ID: d62a3d30fc76
Revises: b2c3d4e5f6a7, f9d645c515d6
Create Date: 2026-06-12 16:03:21.892852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd62a3d30fc76'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', 'f9d645c515d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
