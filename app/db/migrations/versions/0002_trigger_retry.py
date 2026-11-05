"""阶段 1 修订：trigger 重试状态机（attempts / next_attempt_at / last_error / claimed_at / failed）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 0001 建表时命名约定把完整约束名又套了一层前缀，库中实际约束名为：
# ck_trigger_instance_ck_trigger_instance_status_values。
# alembic 的 create_check_constraint 会再次套用命名约定并截断名称，
# 因此这里用显式 SQL 保证约束名与库中实际一致。
_CONSTRAINT = "ck_trigger_instance_ck_trigger_instance_status_values"
_NEW_CHECK = "status IN ('pending', 'claimed', 'fired', 'dropped', 'missed', 'failed')"
_OLD_CHECK = "status IN ('pending', 'claimed', 'fired', 'dropped', 'missed')"


def upgrade() -> None:
    op.add_column("trigger_instance", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("trigger_instance", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trigger_instance", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("trigger_instance", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(f"ALTER TABLE trigger_instance DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE trigger_instance ADD CONSTRAINT {_CONSTRAINT} CHECK ({_NEW_CHECK})"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE trigger_instance DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE trigger_instance ADD CONSTRAINT {_CONSTRAINT} CHECK ({_OLD_CHECK})"
    )
    op.drop_column("trigger_instance", "claimed_at")
    op.drop_column("trigger_instance", "last_error")
    op.drop_column("trigger_instance", "next_attempt_at")
    op.drop_column("trigger_instance", "attempts")
