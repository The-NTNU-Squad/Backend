"""add unlocked_level to users

Revision ID: 0c4e95e477c3
Revises: 3fd26a8ad2a7
Create Date: 2026-08-06 19:03:26.315827

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c4e95e477c3'
down_revision = '3fd26a8ad2a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unlocked_level', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('unlocked_level')
