"""add rate limit counters table

Revision ID: d5b8e2f14c67
Revises: c4a7d1e93b52
Create Date: 2026-10-01 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5b8e2f14c67'
down_revision: Union[str, None] = 'c4a7d1e93b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rate_limit_counters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('window_start', sa.DateTime(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
    )
    # The unique constraint is the concurrency control: the atomic upsert in
    # backend/rate_limit.py targets it, so concurrent attempts cannot race.
    op.create_unique_constraint(
        'uq_rate_limit_bucket_window',
        'rate_limit_counters',
        ['bucket', 'window_start'],
    )
    # Supports the startup sweep that drops expired windows.
    op.create_index(
        'ix_rate_limit_counters_window_start', 'rate_limit_counters', ['window_start']
    )


def downgrade() -> None:
    op.drop_index(
        'ix_rate_limit_counters_window_start', table_name='rate_limit_counters'
    )
    op.drop_constraint(
        'uq_rate_limit_bucket_window', 'rate_limit_counters', type_='unique'
    )
    op.drop_table('rate_limit_counters')
