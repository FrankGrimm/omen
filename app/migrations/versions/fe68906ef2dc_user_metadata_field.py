"""user metadata field

Revision ID: fe68906ef2dc
Revises: 1e8c86cc71f3
Create Date: 2020-07-21 15:22:58.084992

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe68906ef2dc'
down_revision = '1e8c86cc71f3'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('usermetadata', sa.JSON(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'usermetadata')
    # ### end Alembic commands ###
