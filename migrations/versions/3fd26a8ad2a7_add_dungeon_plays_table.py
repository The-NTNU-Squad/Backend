"""add dungeon_plays table

Revision ID: 3fd26a8ad2a7
Revises: 27f87a206115
Create Date: 2026-08-05 19:21:10.998208

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3fd26a8ad2a7'
down_revision = '27f87a206115'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dungeon_plays',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('dungeon_level', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('dungeon_plays')
