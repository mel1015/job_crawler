"""add image_urls to jobs

Revision ID: a1b2c3d4e5f6
Revises: 866a1946d299
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '866a1946d299'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('image_urls', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'image_urls')
