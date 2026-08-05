"""add clear_time_ms to dungeon_rewards

Revision ID: 27f87a206115
Revises: 4f1e7e08bc29
Create Date: 2026-08-05 19:19:23.927636

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '27f87a206115'
down_revision = '4f1e7e08bc29'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('dungeon_rewards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clear_time_ms', sa.BigInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table('dungeon_rewards', schema=None) as batch_op:
        batch_op.drop_column('clear_time_ms')
