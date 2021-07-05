"""task_id keying

Revision ID: f5f00a6a45ea
Revises: 0818749b8790
Create Date: 2021-05-10 09:01:59.047951

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5f00a6a45ea'
down_revision = '0818749b8790'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE annotations SET task_id = -1 WHERE task_id IS NULL;")

    op.alter_column('annotations', 'task_id',
                    existing_type=sa.INTEGER(),
                    nullable=False)

    op.execute("ALTER TABLE annotations DROP CONSTRAINT annotations_pkey")
    op.create_primary_key("annotations_pkey", "annotations",
                          ['owner_id', 'dataset_id', 'sample', 'sample_index', 'task_id'])


def downgrade():
    op.alter_column('annotations', 'task_id',
                    existing_type=sa.INTEGER(),
                    nullable=True)
    op.execute("UPDATE annotations SET task_id = NULL WHERE task_id = -1;")

    op.execute("ALTER TABLE annotations DROP CONSTRAINT annotations_pkey")
    op.create_primary_key("annotations", "annotations_pkey", ['owner_id', 'dataset_id', 'sample', 'sample_index'])
