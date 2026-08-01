"""Add idempotent document ingestion and normalize usernames.

Revision ID: 0003_ingestion_usernames
Revises: 0002_task_leases
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_ingestion_usernames"
down_revision: Union[str, Sequence[str], None] = "0002_task_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("ingestion_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_knowledge_documents_ingestion_id",
        "knowledge_documents",
        ["ingestion_id"],
        unique=True,
    )
    op.execute("UPDATE users SET username = LOWER(TRIM(username))")


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_documents_ingestion_id",
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "ingestion_id")

