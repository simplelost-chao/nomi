"""add memory self-iteration fields

Revision ID: a1b2c3d4e5f6
Revises: 9346fcfb1039
Create Date: 2026-06-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9346fcfb1039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memories', sa.Column('retrieved_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('useful_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('utility_score', sa.Float(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('consolidated_into', sa.Uuid(), nullable=True))
    op.add_column('memories', sa.Column('archived', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    for col in ('archived', 'consolidated_into', 'utility_score', 'useful_count', 'retrieved_count'):
        op.drop_column('memories', col)
