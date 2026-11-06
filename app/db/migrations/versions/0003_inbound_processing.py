"""阶段 1 修订 2：inbound_processing 表（入站事件处理状态，供启动补处理）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: str = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbound_processing",
        sa.Column("event_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('processing', 'done', 'failed')", name="status_values"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_log.id"],
            name=op.f("fk_inbound_processing_event_id_event_log"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_inbound_processing_user_id_user"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_inbound_processing")),
    )
    op.create_index("ix_inbound_processing_status", "inbound_processing", ["status"])


def downgrade() -> None:
    op.drop_index("ix_inbound_processing_status", table_name="inbound_processing")
    op.drop_table("inbound_processing")
