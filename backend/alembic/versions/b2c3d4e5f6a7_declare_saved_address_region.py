"""declare saved address region columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-01 19:00:00.000000

These three columns already exist on the live saved_addresses table (created
outside the migration history) but were never declared in backend/models.py.
Autogenerate therefore reported them as removable, and a database created
from metadata differed from one built by running migrations. This migration
brings a migrated database in line with an existing one.

Written as ADD COLUMN IF NOT EXISTS so it is safe on both kinds of database.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str]] = None
depends_on: Union[str, Sequence[str]] = None


_COLUMNS = (
    ('city', sa.String(length=64)),
    ('state', sa.String(length=64)),
    ('pincode', sa.String(length=10)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.execute(
            f'ALTER TABLE saved_addresses ADD COLUMN IF NOT EXISTS "{name}" '
            f'{type_.compile(dialect=op.get_bind().dialect)}'
        )


def downgrade() -> None:
    for name, _type_ in reversed(_COLUMNS):
        op.execute(f'ALTER TABLE saved_addresses DROP COLUMN IF EXISTS "{name}"')
