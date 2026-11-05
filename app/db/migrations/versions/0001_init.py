"""阶段 1 初始迁移：全部表、pgvector 扩展、event_log append-only 触发器。

Revision ID: 0001
Revises:
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("day_start", sa.Time(), nullable=False),
        sa.Column("rev", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
    )

    op.create_table(
        "channel_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("rev", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_identity")),
        sa.UniqueConstraint("channel", "external_id", name="uq_channel_external"),
        sa.CheckConstraint("channel IN ('feishu', 'console')", name="ck_channel_identity_channel_values"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_channel_identity_user_id_user")
        ),
    )
    op.create_index(
        op.f("ix_channel_identity_user_id"), "channel_identity", ["user_id"], unique=False
    )

    op.create_table(
        "event_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_log")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_event_log_idempotency_key")),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'system', 'tool')",
            name="ck_event_log_direction_values",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_event_log_user_id_user")),
    )
    op.create_index("ix_event_log_user_occurred", "event_log", ["user_id", "occurred_at"], unique=False)
    op.create_index(op.f("ix_event_log_trace_id"), "event_log", ["trace_id"], unique=False)

    op.create_table(
        "work_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("mission_id", sa.Uuid(), nullable=True),
        sa.Column("clarity_score", sa.Float(), nullable=True),
        sa.Column("size_estimate_min", sa.Integer(), nullable=True),
        sa.Column("revisit_trigger", postgresql.JSONB(), nullable=True),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("rev", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item")),
        sa.CheckConstraint("type IN ('seed', 'item', 'project', 'mission')", name="ck_work_item_type_values"),
        sa.CheckConstraint(
            "status IN ('seed', 'clarifying', 'active', 'dormant', 'done', 'dropped')",
            name="ck_work_item_status_values",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_work_item_user_id_user")),
        sa.ForeignKeyConstraint(["parent_id"], ["work_item.id"], name=op.f("fk_work_item_parent_id_work_item")),
        sa.ForeignKeyConstraint(["mission_id"], ["work_item.id"], name=op.f("fk_work_item_mission_id_work_item")),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["event_log.id"], name=op.f("fk_work_item_source_event_id_event_log")
        ),
    )
    op.create_index(op.f("ix_work_item_user_id"), "work_item", ["user_id"], unique=False)

    op.create_table(
        "planned_block",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("assigned_by", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("energy", sa.Text(), nullable=True),
        sa.Column("compressible", sa.Boolean(), nullable=False),
        sa.Column("plan_rev", sa.Integer(), nullable=True),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rev", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_block")),
        sa.CheckConstraint(
            "status IN ('planned', 'done', 'skipped', 'moved')", name="ck_planned_block_status_values"
        ),
        sa.CheckConstraint(
            "assigned_by IN ('user', 'friday', 'jarvis')", name="ck_planned_block_assigned_by_values"
        ),
        sa.CheckConstraint(
            "difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="ck_planned_block_difficulty_range"
        ),
        sa.CheckConstraint(
            "energy IS NULL OR energy IN ('low', 'mid', 'high')", name="ck_planned_block_energy_values"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_planned_block_user_id_user")),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["work_item.id"], name=op.f("fk_planned_block_work_item_id_work_item")
        ),
    )
    op.create_index(op.f("ix_planned_block_user_id"), "planned_block", ["user_id"], unique=False)

    op.create_table(
        "trigger_instance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tz", sa.Text(), nullable=False),
        sa.Column("precondition", postgresql.JSONB(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("plan_rev", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trigger_instance")),
        sa.UniqueConstraint("key", name=op.f("uq_trigger_instance_key")),
        sa.CheckConstraint(
            "kind IN ('reminder', 'brief_morning', 'brief_evening', 'block_start', 'overdue_check')",
            name="ck_trigger_instance_kind_values",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'fired', 'dropped', 'missed')",
            name="ck_trigger_instance_status_values",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_trigger_instance_user_id_user")),
    )
    op.create_index(
        "ix_trigger_instance_status_fire_at", "trigger_instance", ["status", "fire_at"], unique=False
    )
    op.create_index(op.f("ix_trigger_instance_user_id"), "trigger_instance", ["user_id"], unique=False)

    op.create_table(
        "nudge_candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("class", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("value_score", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("precondition", postgresql.JSONB(), nullable=True),
        sa.Column("source_trigger_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nudge_candidate")),
        sa.CheckConstraint(
            "class IN ('commitment', 'brief', 'suggestion')", name="ck_nudge_candidate_class_values"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_nudge_candidate_user_id_user")),
        sa.ForeignKeyConstraint(
            ["source_trigger_id"],
            ["trigger_instance.id"],
            name=op.f("fk_nudge_candidate_source_trigger_id_trigger_instance"),
        ),
    )
    op.create_index(op.f("ix_nudge_candidate_user_id"), "nudge_candidate", ["user_id"], unique=False)
    op.create_index(op.f("ix_nudge_candidate_dedupe_key"), "nudge_candidate", ["dedupe_key"], unique=False)

    op.create_table(
        "nudge_decision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("gate_reasons", postgresql.JSONB(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("budget_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nudge_decision")),
        sa.CheckConstraint("decision IN ('send', 'defer', 'merge', 'drop')", name="ck_nudge_decision_decision_values"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["nudge_candidate.id"], name=op.f("fk_nudge_decision_candidate_id_nudge_candidate")
        ),
    )
    op.create_index(op.f("ix_nudge_decision_candidate_id"), "nudge_decision", ["candidate_id"], unique=False)

    op.create_table(
        "delivery",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("provider_msg_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery")),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["nudge_decision.id"], name=op.f("fk_delivery_decision_id_nudge_decision")
        ),
    )
    op.create_index(op.f("ix_delivery_decision_id"), "delivery", ["decision_id"], unique=False)

    op.create_table(
        "notif_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("daily_budget", sa.Integer(), nullable=False),
        sa.Column("quiet_hours", postgresql.JSONB(), nullable=True),
        sa.Column("class_enabled", postgresql.JSONB(), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notif_prefs")),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_notif_prefs_user_id_user")),
    )

    op.create_table(
        "llm_call",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("request", postgresql.JSONB(), nullable=True),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_call")),
    )
    op.create_index(op.f("ix_llm_call_trace_id"), "llm_call", ["trace_id"], unique=False)
    op.create_index(op.f("ix_llm_call_user_id"), "llm_call", ["user_id"], unique=False)

    op.create_table(
        "memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mission_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("slot_key", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("polarity", sa.Text(), nullable=True),
        sa.Column("scope", postgresql.JSONB(), nullable=True),
        sa.Column("source_class", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("support_days", sa.Integer(), nullable=True),
        sa.Column("contradict_count", sa.Integer(), nullable=True),
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppress_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory")),
        sa.CheckConstraint("type IN ('slot', 'preference', 'episode', 'state_signal')", name="ck_memory_type_values"),
        sa.CheckConstraint(
            "source_class IN ('confirmed', 'stated', 'inferred')", name="ck_memory_source_class_values"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retracted', 'pending')", name="ck_memory_status_values"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_memory_user_id_user")),
        sa.ForeignKeyConstraint(["mission_id"], ["work_item.id"], name=op.f("fk_memory_mission_id_work_item")),
        sa.ForeignKeyConstraint(["supersedes_id"], ["memory.id"], name=op.f("fk_memory_supersedes_id_memory")),
    )
    op.create_index(op.f("ix_memory_user_id"), "memory", ["user_id"], unique=False)

    op.create_table(
        "memory_source",
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("memory_id", "event_id", name=op.f("pk_memory_source")),
        sa.ForeignKeyConstraint(["memory_id"], ["memory.id"], name=op.f("fk_memory_source_memory_id_memory")),
        sa.ForeignKeyConstraint(
            ["event_id"], ["event_log.id"], name=op.f("fk_memory_source_event_id_event_log")
        ),
    )

    op.create_table(
        "memory_decision_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("candidate", postgresql.JSONB(), nullable=True),
        sa.Column("neighbors", postgresql.JSONB(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("alias", sa.Text(), nullable=True),
        sa.Column("llm_call_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_decision_log")),
        sa.CheckConstraint(
            "action IN ('ADD', 'SUPERSEDE', 'NOOP', 'MERGE', 'ASK')", name="ck_memory_decision_log_action_values"
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memory.id"], name=op.f("fk_memory_decision_log_memory_id_memory")),
        sa.ForeignKeyConstraint(
            ["llm_call_id"], ["llm_call.id"], name=op.f("fk_memory_decision_log_llm_call_id_llm_call")
        ),
    )
    op.create_index(op.f("ix_memory_decision_log_memory_id"), "memory_decision_log", ["memory_id"], unique=False)

    # event_log append-only：数据库层面禁止 UPDATE 与 DELETE
    op.execute(
        """
        CREATE FUNCTION forbid_event_log_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'event_log is append-only: % is not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER event_log_append_only
        BEFORE UPDATE OR DELETE ON event_log
        FOR EACH ROW EXECUTE FUNCTION forbid_event_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS event_log_append_only ON event_log")
    op.execute("DROP FUNCTION IF EXISTS forbid_event_log_mutation()")
    op.drop_table("memory_decision_log")
    op.drop_table("memory_source")
    op.drop_index(op.f("ix_memory_user_id"), table_name="memory")
    op.drop_table("memory")
    op.drop_index(op.f("ix_llm_call_user_id"), table_name="llm_call")
    op.drop_index(op.f("ix_llm_call_trace_id"), table_name="llm_call")
    op.drop_table("llm_call")
    op.drop_table("notif_prefs")
    op.drop_index(op.f("ix_delivery_decision_id"), table_name="delivery")
    op.drop_table("delivery")
    op.drop_index(op.f("ix_nudge_decision_candidate_id"), table_name="nudge_decision")
    op.drop_table("nudge_decision")
    op.drop_index(op.f("ix_nudge_candidate_dedupe_key"), table_name="nudge_candidate")
    op.drop_index(op.f("ix_nudge_candidate_user_id"), table_name="nudge_candidate")
    op.drop_table("nudge_candidate")
    op.drop_index(op.f("ix_trigger_instance_user_id"), table_name="trigger_instance")
    op.drop_index("ix_trigger_instance_status_fire_at", table_name="trigger_instance")
    op.drop_table("trigger_instance")
    op.drop_index(op.f("ix_planned_block_user_id"), table_name="planned_block")
    op.drop_table("planned_block")
    op.drop_index(op.f("ix_work_item_user_id"), table_name="work_item")
    op.drop_table("work_item")
    op.drop_index(op.f("ix_event_log_trace_id"), table_name="event_log")
    op.drop_index("ix_event_log_user_occurred", table_name="event_log")
    op.drop_table("event_log")
    op.drop_index(op.f("ix_channel_identity_user_id"), table_name="channel_identity")
    op.drop_table("channel_identity")
    op.drop_table("user")
    op.execute("DROP EXTENSION IF EXISTS vector")
