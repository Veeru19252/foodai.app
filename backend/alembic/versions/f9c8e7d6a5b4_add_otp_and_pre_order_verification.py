"""add otp codes and pre-order verification columns

Revision ID: f9c8e7d6a5b4
Revises: e7d4a6f2b8c1
Create Date: 2026-08-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9c8e7d6a5b4'
down_revision: Union[str, None] = 'e7d4a6f2b8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'otp_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phone', sa.String(length=15), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_otp_codes_phone', 'otp_codes', ['phone'])
    op.add_column('users', sa.Column('phone', sa.String(length=15), nullable=True))
    op.add_column('users', sa.Column('phone_verified_at', sa.DateTime(), nullable=True))
    op.add_column('orders', sa.Column('phone_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('orders', sa.Column('location_confirmed', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('orders', sa.Column('location_confirm_lat', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column('location_confirm_lng', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'location_confirm_lng')
    op.drop_column('orders', 'location_confirm_lat')
    op.drop_column('orders', 'location_confirmed')
    op.drop_column('orders', 'phone_verified')
    op.drop_column('users', 'phone_verified_at')
    op.drop_column('users', 'phone')
    op.drop_index('ix_otp_codes_phone', table_name='otp_codes')
    op.drop_table('otp_codes')
