"""star counts (BPASS numbers-* tables)

Revision ID: b4c2e91a7d10
Revises: 7751d6e64a35
Create Date: 2026-09-11 14:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4c2e91a7d10"
down_revision = "7751d6e64a35"
branch_labels = None
depends_on = None

_COUNT_COLS = (
    "n_o_hi",
    "n_of_hi",
    "n_b_hi",
    "n_a_hi",
    "n_ysg_hi",
    "n_k_hi",
    "n_m_hi",
    "n_wnh_hi",
    "n_wn_hi",
    "n_wc_hi",
    "n_o_lo",
    "n_of_lo",
    "n_b_lo",
    "n_a_lo",
    "n_ysg_lo",
    "n_k_lo",
    "n_m_lo",
    "n_wnh_lo",
    "n_wn_lo",
    "n_wc_lo",
)


def upgrade() -> None:
    op.create_table(
        "star_counts",
        sa.Column("population_id", sa.Integer(), nullable=False),
        sa.Column("age_index", sa.SmallInteger(), nullable=False),
        sa.Column("log_age", sa.Float(precision=53), nullable=False),
        *[sa.Column(name, sa.Float(precision=53), nullable=False) for name in _COUNT_COLS],
        sa.ForeignKeyConstraint(
            ["population_id"],
            ["population.id"],
            name=op.f("fk_star_counts_population_id_population"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("population_id", "age_index", name=op.f("pk_star_counts")),
    )


def downgrade() -> None:
    op.drop_table("star_counts")
