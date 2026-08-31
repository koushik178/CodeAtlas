"""Add nullable pgvector embeddings to stored code chunks.

Revision ID: 20260829_01
Revises:
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa

revision = "20260829_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "code_chunks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("code_chunks")}
    if "embedding" not in columns:
        op.execute("ALTER TABLE code_chunks ADD COLUMN embedding vector(1536)")
    if "embedding_model" not in columns:
        op.add_column("code_chunks", sa.Column("embedding_model", sa.String(length=100), nullable=True))


def downgrade() -> None:
    # Deliberately no destructive downgrade: embeddings may be expensive to regenerate.
    pass
