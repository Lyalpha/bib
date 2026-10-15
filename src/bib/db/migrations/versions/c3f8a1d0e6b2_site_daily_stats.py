"""site daily stats

Revision ID: c3f8a1d0e6b2
Revises: b4c2e91a7d10
Create Date: 2026-09-12 10:21:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f8a1d0e6b2"
down_revision = "b4c2e91a7d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_daily_stat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_daily_stat")),
        sa.UniqueConstraint("day", "path", name="uq_site_daily_stat_day_path"),
    )


def downgrade() -> None:
    op.drop_table("site_daily_stat")
