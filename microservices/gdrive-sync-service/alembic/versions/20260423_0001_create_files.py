"""create files table

Revision ID: 20260423_0001
Revises:
Create Date: 2026-04-23

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260423_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("drive_name", sa.String(length=128), nullable=False),
        sa.Column("file_id", sa.String(length=128), nullable=False),
        sa.Column("file_name", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("minio_path", sa.String(length=2048), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=4096), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drive_name", "file_id", name="uq_files_drive_file_id"),
    )
    op.create_index("ix_files_drive_name", "files", ["drive_name"], unique=False)
    op.create_index("ix_files_status", "files", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_status", table_name="files")
    op.drop_index("ix_files_drive_name", table_name="files")
    op.drop_table("files")
