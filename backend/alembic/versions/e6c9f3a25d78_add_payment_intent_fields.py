"""add payment intent fields to orders

Revision ID: e6c9f3a25d78
Revises: d5b8e2f14c67
Create Date: 2026-10-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6c9f3a25d78'
down_revision: Union[str, None] = 'd5b8e2f14c67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'orders',
        sa.Column('payment_provider_order_id', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'orders', sa.Column('payment_amount_paise', sa.Integer(), nullable=True)
    )
    op.add_column(
        'orders', sa.Column('payment_currency', sa.String(length=8), nullable=True)
    )
    op.add_column(
        'orders', sa.Column('payment_created_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'orders', sa.Column('payment_verified_at', sa.DateTime(), nullable=True)
    )
    # A captured provider payment id may settle at most one order. NULLs (COD
    # and unpaid orders) are exempt under PostgreSQL's unique semantics.
    op.create_unique_constraint('uq_orders_payment_id', 'orders', ['payment_id'])


def downgrade() -> None:
    op.drop_constraint('uq_orders_payment_id', 'orders', type_='unique')
    op.drop_column('orders', 'payment_verified_at')
    op.drop_column('orders', 'payment_created_at')
    op.drop_column('orders', 'payment_currency')
    op.drop_column('orders', 'payment_amount_paise')
    op.drop_column('orders', 'payment_provider_order_id')
