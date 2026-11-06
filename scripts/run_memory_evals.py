"""记忆评测（手动运行，真实 LLM + 真实 Ollama，不进 CI）。

用法：
    make ollama-pull && make check-embedding
    uv run python scripts/run_memory_evals.py [--cases PATH] [--limit N]

数据库默认使用 butler_test，可用 MEMORY_EVAL_DATABASE_URL 覆盖，避免污染 butler。
输出：逐类抽取 precision/recall、错记率、裁决混淆矩阵、时间归一化准确率；
每次运行的指标与模型 id 追加到 tests/evals/results.jsonl。
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path

import yaml
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

EVAL_DATABASE_URL = os.environ.get(
    "MEMORY_EVAL_DATABASE_URL",
    "postgresql+psycopg://butler:butler@localhost:5432/butler_test",
)
os.environ["DATABASE_URL"] = EVAL_DATABASE_URL

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402

from app.core.clock import FakeClock  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.ids import new_uuid7  # noqa: E402
from app.db.base import make_engine, make_sessionmaker  # noqa: E402
from app.db.models import (  # noqa: E402
    EventLog,
    LLMCall,
    Memory,
    MemoryDecisionLog,
    MemoryExtractionRun,
    User,
)
from app.embeddings.service import build_embedding_service  # noqa: E402
from app.llm.gateway import LLMGateway  # noqa: E402
from app.llm.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from app.memory.extract import EXTRACTOR_VERSION  # noqa: E402
from app.memory.runs import process_run  # noqa: E402
from app.memory.weights import initial_weight  # noqa: E402

RESULTS_PATH = PROJECT_ROOT / "tests" / "evals" / "results.jsonl"


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).lower()


def _migrate() -> None:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


def _build_gateway(settings: Settings, sessionmaker) -> LLMGateway:
    return LLMGateway(
        aliases_path=settings.aliases_path,
        providers={
            "openai_compat": OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key),
            "openai_compat_agent": OpenAICompatProvider(
                settings.llm_agent_base_url, settings.llm_agent_api_key
            ),
        },
        sessionmaker=sessionmaker,
        clock=FakeClock(dt.datetime.fromisoformat("2026-11-06T10:00:00+08:00")),
        daily_limit=settings.llm_daily_limit,
    )


def _matches(expected: dict, memory: dict) -> bool:
    if memory.get("type") != expected.get("type"):
        return False
    if "slot_key" in expected and memory.get("slot_key") != expected.get("slot_key"):
        return False
    if "subject" in expected and _normalize(memory.get("subject")) != _normalize(
        expected["subject"]
    ):
        return False
    value = memory.get("value") or {}
    if "time" in expected and value.get("time") != expected["time"]:
        return False
    if "value_text" in expected:
        actual_text = _normalize(value.get("text"))
        wanted = _normalize(expected["value_text"])
        if wanted not in actual_text and actual_text not in wanted:
            return False
    scope = memory.get("scope") or {}
    if "scope_kind" in expected and scope.get("kind") != expected["scope_kind"]:
        return False
    if "scope_date" in expected and scope.get("date") != expected["scope_date"]:
        return False
    if "source_class" in expected and memory.get("source_class") != expected["source_class"]:
        return False
    return True


async def _seed_memory(
    session, user: User, seed: dict, clock: FakeClock, embedder
) -> None:
    value = {"text": seed.get("value_text", "")}
    if seed.get("time"):
        value["time"] = seed["time"]
    scope = {"kind": seed.get("scope_kind", "persistent")}
    if seed.get("scope_date"):
        scope["date"] = seed["scope_date"]
    source_class = seed.get("source_class", "stated")
    embedding = None
    embedding_model = None
    if embedder is not None:
        try:
            text = f"{seed.get('type')} {seed.get('slot_key') or ''} {seed.get('subject','')} {seed.get('value_text','')}"
            embedding = await embedder.embed_one(text)
            embedding_model = embedder.model_name
        except Exception:
            embedding = None
    suppress_until = (
        clock.now() + dt.timedelta(days=int(seed["suppress_days"]))
        if seed.get("suppress_days")
        else None
    )
    session.add(
        Memory(
            user_id=user.id,
            type=seed.get("type", "preference"),
            slot_key=seed.get("slot_key"),
            subject=seed.get("subject", ""),
            value=value,
            scope=scope,
            source_class=source_class,
            weight=initial_weight(source_class),
            confidence=0.8,
            status=seed.get("status", "active"),
            recorded_at=clock.now(),
            valid_from=clock.now(),
            support_days=1,
            contradict_count=0,
            last_reinforced_at=clock.now(),
            suppress_until=suppress_until,
            embedding=embedding,
            embedding_model=embedding_model,
        )
    )


async def _run_case(
    sessionmaker, gateway, embedder, settings: Settings, case: dict, meta: dict
) -> dict:
    clock = FakeClock(dt.datetime.fromisoformat(meta["now"]))
    texts = case.get("texts") or [case["text"]]
    user = User(
        display_name=f"eval-{case['id']}-{uuid.uuid4().hex[:6]}",
        timezone=meta.get("tz", "Asia/Shanghai"),
        day_start=dt.time(4, 0),
        rev=1,
    )
    async with sessionmaker() as session:
        session.add(user)
        await session.flush()
        events: list[EventLog] = []
        for index, text in enumerate(texts):
            event = EventLog(
                user_id=user.id,
                channel="console",
                direction="inbound",
                type="message",
                payload={"text": text},
                trace_id=f"eval-{case['id']}-{index}",
                occurred_at=clock.now() + dt.timedelta(minutes=index),
                recorded_at=clock.now(),
            )
            session.add(event)
            events.append(event)
        await session.flush()
        for seed in case.get("seed") or []:
            await _seed_memory(session, user, seed, clock, embedder)
        run = MemoryExtractionRun(
            id=new_uuid7(),
            user_id=user.id,
            to_event_id=events[-1].id,
            extractor_version=EXTRACTOR_VERSION,
            event_count=len(events),
            status="pending",
            stats={},
            created_at=clock.now(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id
        user_id = user.id

    await process_run(
        sessionmaker,
        run_id,
        gateway=gateway,
        embedder=embedder,
        clock=clock,
        settings=settings,
    )

    async with sessionmaker() as session:
        logs = (
            await session.execute(
                select(MemoryDecisionLog).where(MemoryDecisionLog.run_id == run_id)
            )
        ).scalars().all()
        written: list[Memory] = []
        pending: list[Memory] = []
        for log in logs:
            if log.memory_id is None:
                continue
            memory = await session.get(Memory, log.memory_id)
            if memory is None:
                continue
            if log.action in ("ADD", "SUPERSEDE"):
                written.append(memory)
            elif log.action == "ASK":
                pending.append(memory)
        run_row = await session.get(MemoryExtractionRun, run_id)

    return {
        "actions": [log.action for log in logs],
        "reasons": [log.reason for log in logs],
        "written": [
            {
                "id": str(memory.id),
                "type": memory.type,
                "slot_key": memory.slot_key,
                "subject": memory.subject,
                "value": memory.value,
                "scope": memory.scope,
                "source_class": memory.source_class,
                "time": (memory.value or {}).get("time"),
            }
            for memory in written
        ],
        "pending": [
            {"id": str(memory.id), "type": memory.type, "slot_key": memory.slot_key}
            for memory in pending
        ],
        "run_status": run_row.status if run_row else "missing",
        "user_id": str(user_id),
    }


def _score(cases: list[dict], results: list[dict]) -> dict:
    per_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    written_total = 0
    wrong_total = 0
    action_checked = 0
    action_correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    time_checked = 0
    time_correct = 0
    for case, result in zip(cases, results, strict=False):
        expected = case.get("expect") or []
        actual = result["written"]
        written_total += len(actual)
        used: set[int] = set()
        for want in expected:
            matched = next(
                (
                    index
                    for index, memory in enumerate(actual)
                    if index not in used and _matches(want, memory)
                ),
                None,
            )
            type_key = str(want.get("type", "unknown"))
            if matched is None:
                per_type[type_key]["fn"] += 1
            else:
                used.add(matched)
                per_type[type_key]["tp"] += 1
        for index, memory in enumerate(actual):
            if index in used:
                continue
            per_type[memory["type"]]["fp"] += 1
            wrong_total += 1

        expected_action = case.get("expected_action")
        if expected_action:
            action_checked += 1
            actual_action = (result["actions"] or ["NONE"])[0]
            confusion[expected_action][actual_action] += 1
            if actual_action == expected_action:
                action_correct += 1

        check = case.get("check_time")
        if check:
            time_checked += 1
            if any(
                memory.get("slot_key") == check.get("slot_key")
                and memory.get("time") == check.get("time")
                for memory in actual
            ):
                time_correct += 1

    tp = sum(values["tp"] for values in per_type.values())
    fp = sum(values["fp"] for values in per_type.values())
    fn = sum(values["fn"] for values in per_type.values())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "wrong_memory_rate": round(wrong_total / written_total, 4) if written_total else 0.0,
        "by_type": {key: dict(value) for key, value in per_type.items()},
        "resolve_confusion": {key: dict(value) for key, value in confusion.items()},
        "action_accuracy": round(action_correct / action_checked, 4) if action_checked else 0.0,
        "time_accuracy": round(time_correct / time_checked, 4) if time_checked else 0.0,
        "cases": len(results),
    }


async def main_async(args: argparse.Namespace) -> int:
    settings = Settings()
    cfg = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    meta = cfg["meta"]
    cases = cfg["cases"][: args.limit] if args.limit else cfg["cases"]
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    gateway = _build_gateway(settings, sessionmaker)
    embedder = build_embedding_service(settings)

    print(f"记忆评测：now={meta['now']} tz={meta['tz']} cases={len(cases)} db={settings.database_url}")
    results: list[dict] = []
    for case in cases:
        try:
            result = await _run_case(sessionmaker, gateway, embedder, settings, case, meta)
            results.append(result)
            status = "PASS" if not (case.get("expect") and not result["written"]) else "DONE"
            print(f"[{status}] {case['id']} actions={result['actions']} written={len(result['written'])}")
        except Exception as exc:
            print(f"[FAIL] {case['id']} 异常：{type(exc).__name__}: {exc}")
            results.append(
                {"actions": [], "reasons": [], "written": [], "pending": [], "run_status": "error"}
            )

    metrics = _score(cases, results)
    eval_user_ids = [
        uuid.UUID(str(result["user_id"]))
        for result in results
        if result.get("user_id")
    ]
    async with sessionmaker() as session:
        model_rows = (
            await session.execute(
                select(LLMCall.alias, LLMCall.model_id)
                .where(LLMCall.user_id.in_(eval_user_ids))
                .distinct()
            )
        ).all() if eval_user_ids else []
    metrics["models"] = [{"alias": alias, "model_id": model_id} for alias, model_id in model_rows]
    metrics["embedding_model"] = embedder.model_name
    metrics["ts"] = dt.datetime.now(dt.UTC).isoformat()
    metrics["case_file"] = str(Path(args.cases).name)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics, ensure_ascii=False) + "\n")

    print("\n汇总")
    for key in ("precision", "recall", "wrong_memory_rate", "action_accuracy", "time_accuracy"):
        print(f"  {key}: {metrics[key]}")
    print(f"  by_type: {metrics['by_type']}")
    print(f"  resolve_confusion: {metrics['resolve_confusion']}")
    print(f"  结果已追加：{RESULTS_PATH}")
    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="记忆评测（真实模型，手动运行）")
    parser.add_argument(
        "--cases", default=str(PROJECT_ROOT / "tests" / "evals" / "memory_cases.yaml")
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    _migrate()  # 同步执行，避免与 asyncio.run 嵌套
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
