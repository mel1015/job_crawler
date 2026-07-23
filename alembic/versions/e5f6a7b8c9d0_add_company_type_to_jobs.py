"""add company_type to jobs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22

"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("company_type", sa.String(length=16), nullable=True))
    op.add_column("jobs", sa.Column("company_type_signals", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "company_type_signals")
    op.drop_column("jobs", "company_type")
