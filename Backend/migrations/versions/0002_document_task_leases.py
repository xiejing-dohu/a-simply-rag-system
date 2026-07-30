"""Add durable multi-worker leases to document tasks.

Revision ID: 0002_task_leases
Revises: 0001_current_schema
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_task_leases"
down_revision: Union[str, Sequence[str], None] = "0001_current_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_tasks",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "document_tasks",
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_document_tasks_heartbeat_at",
        "document_tasks",
        ["heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_tasks_heartbeat_at", table_name="document_tasks")
    op.drop_column("document_tasks", "heartbeat_at")
    op.drop_column("document_tasks", "attempts")
