"""阶段 3a：记忆写入管线（抽取 run、决策日志归属字段、记忆索引）。

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06

安全说明：memory_decision_log 在阶段 1 只建表、从未写入。加 NOT NULL 前仍执行
「memory_id → memory.user_id → candidate.user_id → 唯一用户兜底」回填，
最后删除仍无法归属的存量测试行并记录警告，避免存量脏数据导致部署中断。
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.create_table(
        "memory_extraction_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", name="fk_memory_extraction_run_user_id_user"),
            nullable=False,
        ),
        sa.Column(
            "to_event_id",
            sa.Uuid(),
            sa.ForeignKey("event_log.id", name="fk_memory_extraction_run_to_event_id_event_log"),
            nullable=False,
        ),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "stats",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'failed')",
            name="ck_memory_extraction_run_status_values",
        ),
        sa.UniqueConstraint(
            "user_id", "to_event_id", "extractor_version",
            name="uq_memory_extraction_run_target",
        ),
    )

    # 决策日志归属字段：先加可空列，回填后再收紧
    op.add_column("memory_decision_log", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("memory_decision_log", sa.Column("run_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE memory_decision_log AS d SET user_id = m.user_id "
            "FROM memory AS m WHERE d.memory_id = m.id AND d.user_id IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE memory_decision_log SET user_id = (candidate->>'user_id')::uuid "
            "WHERE user_id IS NULL AND candidate->>'user_id' ~ '^[0-9a-fA-F-]{36}$'"
        )
    )
    user_count = bind.execute(sa.text('SELECT count(*) FROM "user"')).scalar_one()
    if user_count == 1:
        # 测试库常见情形：只剩一个用户，存量测试日志可安全归属
        bind.execute(
            sa.text(
                'UPDATE memory_decision_log SET user_id = (SELECT id FROM "user" LIMIT 1) '
                "WHERE user_id IS NULL"
            )
        )
    remaining = bind.execute(
        sa.text("SELECT count(*) FROM memory_decision_log WHERE user_id IS NULL")
    ).scalar_one()
    if remaining:
        logger.warning(
            "deleting %d orphan memory_decision_log rows without resolvable user", remaining
        )
        bind.execute(sa.text("DELETE FROM memory_decision_log WHERE user_id IS NULL"))

    op.alter_column("memory_decision_log", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_memory_decision_log_user_id_user",
        "memory_decision_log", "user", ["user_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_memory_decision_log_run_id_memory_extraction_run",
        "memory_decision_log", "memory_extraction_run", ["run_id"], ["id"],
    )
    op.create_index("ix_memory_decision_log_user_id", "memory_decision_log", ["user_id"])
    op.create_index("ix_memory_decision_log_run_id", "memory_decision_log", ["run_id"])

    op.create_index("ix_memory_user_status", "memory", ["user_id", "status"])
    op.create_index("ix_memory_user_type_slot", "memory", ["user_id", "type", "slot_key"])
    op.execute(
        "CREATE INDEX ix_memory_embedding_hnsw ON memory "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_embedding_hnsw")
    op.drop_index("ix_memory_user_type_slot", table_name="memory")
    op.drop_index("ix_memory_user_status", table_name="memory")

    op.drop_index("ix_memory_decision_log_run_id", table_name="memory_decision_log")
    op.drop_index("ix_memory_decision_log_user_id", table_name="memory_decision_log")
    op.drop_constraint(
        "fk_memory_decision_log_run_id_memory_extraction_run",
        "memory_decision_log", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_memory_decision_log_user_id_user", "memory_decision_log", type_="foreignkey",
    )
    op.drop_column("memory_decision_log", "run_id")
    op.drop_column("memory_decision_log", "user_id")
    op.drop_table("memory_extraction_run")
