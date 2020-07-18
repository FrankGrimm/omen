"""activity entity

Revision ID: 1e8c86cc71f3
Revises: 1ca4bedd391b
Create Date: 2020-07-18 22:02:51.033635

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1e8c86cc71f3'
down_revision = '1ca4bedd391b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_foreign_key(None, 'activity', 'users', ['owner_id'], ['uid'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'activity', type_='foreignkey')
    # ### end Alembic commands ###
