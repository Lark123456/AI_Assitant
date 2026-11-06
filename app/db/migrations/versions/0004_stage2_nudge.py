"""阶段 2：nudge 表字段扩充（简报偏好、候选标记、defer 计数）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 简报偏好：默认值与契约一致（08:30 / 21:00 / 开启）
    op.add_column(
        "notif_prefs",
        sa.Column(
            "morning_brief_time", sa.Time(), nullable=False, server_default=sa.text("'08:30'")
        ),
    )
    op.add_column(
        "notif_prefs",
        sa.Column(
            "evening_brief_time", sa.Time(), nullable=False, server_default=sa.text("'21:00'")
        ),
    )
    op.add_column(
        "notif_prefs",
        sa.Column("briefs_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # 候选标记：explicit 与合并落点；holdout/propensity 本阶段只留字段
    op.add_column(
        "nudge_candidate",
        sa.Column("explicit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("nudge_candidate", sa.Column("holdout_group", sa.Text(), nullable=True))
    op.add_column("nudge_candidate", sa.Column("propensity", sa.Float(), nullable=True))
    op.add_column(
        "nudge_candidate",
        sa.Column("merged_into_candidate_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_nudge_candidate_merged_into_candidate_id_nudge_candidate"),
        "nudge_candidate",
        "nudge_candidate",
        ["merged_into_candidate_id"],
        ["id"],
    )

    # defer 计数：仲裁延后不消耗 attempts，最多 3 次
    op.add_column(
        "trigger_instance",
        sa.Column("defer_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("trigger_instance", "defer_count")
    op.drop_constraint(
        op.f("fk_nudge_candidate_merged_into_candidate_id_nudge_candidate"),
        "nudge_candidate",
        type_="foreignkey",
    )
    op.drop_column("nudge_candidate", "merged_into_candidate_id")
    op.drop_column("nudge_candidate", "propensity")
    op.drop_column("nudge_candidate", "holdout_group")
    op.drop_column("nudge_candidate", "explicit")
    op.drop_column("notif_prefs", "briefs_enabled")
    op.drop_column("notif_prefs", "evening_brief_time")
    op.drop_column("notif_prefs", "morning_brief_time")
