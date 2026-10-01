"""add idempotency records table

Revision ID: c4a7d1e93b52
Revises: f9c8e7d6a5b4
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a7d1e93b52'
down_revision: Union[str, None] = 'f9c8e7d6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('endpoint', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('order_ids', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    # This constraint is the entire concurrency control mechanism, not an
    # integrity nicety. Two in-flight requests with the same key both insert;
    # the second blocks here until the first commits (then replays) or rolls
    # back (then proceeds). It is what makes duplicate order creation
    # impossible without any cross-process coordination.
    op.create_unique_constraint(
        'uq_idempotency_user_endpoint_key',
        'idempotency_records',
        ['user_id', 'endpoint', 'key'],
    )
    # Supports the expiry sweep that keeps this table from growing forever.
    op.create_index(
        'ix_idempotency_records_created_at', 'idempotency_records', ['created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_idempotency_records_created_at', table_name='idempotency_records')
    op.drop_constraint(
        'uq_idempotency_user_endpoint_key', 'idempotency_records', type_='unique'
    )
    op.drop_table('idempotency_records')
