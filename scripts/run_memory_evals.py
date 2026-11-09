"""记忆评测（手动运行，真实 LLM + 真实 Ollama，不进 CI）。

用法：
    make ollama-pull && make check-embedding
    uv run python scripts/run_memory_evals.py [--cases PATH] [--limit N]
    uv run python scripts/run_memory_evals.py --check-cases [--cases PATH]
    uv run python scripts/run_memory_evals.py --resume RAW [--cases PATH]
    uv run python scripts/run_memory_evals.py --score-from RAW [--cases PATH]

数据库默认使用 butler_test，可用 MEMORY_EVAL_DATABASE_URL 覆盖，避免污染 butler。
输出：逐类抽取 precision/recall、错记率、裁决混淆矩阵、时间归一化准确率、
拒绝准确率；指标追加到 tests/evals/results.jsonl，逐条原始输出写入
tests/evals/runs/*.jsonl，可用 --score-from 离线重算。
"""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import subprocess
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
# 评测放宽每日限额：每条用例独立用户，但仍避免长跑被限额截断
os.environ.setdefault("LLM_DAILY_LIMIT", "0")

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

HARNESS_VERSION = "memory-eval-v2"
ABORT_ERROR_RATE = 0.05  # error 类失败占比超过 5% 时中止
RESULTS_PATH = PROJECT_ROOT / "tests" / "evals" / "results.jsonl"
RUNS_DIR = PROJECT_ROOT / "tests" / "evals" / "runs"
REJECT_PREFIX = "rejected:"


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).lower()


def _migrate() -> None:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


def _git_state() -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
        )
        return sha, bool(status.strip())
    except Exception:
        return None, None


def _resolve_git_state(override_sha: str | None, override_dirty: bool) -> tuple[str, bool]:
    """git 不可用时必须显式指定 --git-sha；避免记录空的溯源信息。"""
    if override_sha:
        return override_sha, override_dirty
    sha, dirty = _git_state()
    if sha is None or dirty is None:
        raise SystemExit(
            "无法获取 git_sha/dirty：当前环境没有可用的 git。"
            "请在仓库内运行，或用 --git-sha 显式指定提交（可加 --git-dirty 标记未提交改动）。"
        )
    return sha, dirty


def _check_scope_kinds(case: dict) -> None:
    """scope_kind 必须是字符串：YAML 会把裸 on/off 解析成布尔值。"""
    for section in ("expect", "seed"):
        items = case.get(section) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            if "scope_kind" in item and not isinstance(item["scope_kind"], str):
                raise SystemExit(
                    f"用例 {case.get('id')} 的 {section}.scope_kind 不是字符串："
                    f"{item['scope_kind']!r}（请给 YAML 值加引号，如 'on'）"
                )


def load_cases(path: Path) -> tuple[dict, str]:
    """加载用例并做结构校验；返回 (配置, 文件 sha256)。"""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    cfg = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(cfg, dict) or "cases" not in cfg or "meta" not in cfg:
        raise SystemExit(f"用例文件结构不合法：{path}")
    cases = cfg["cases"]
    if not isinstance(cases, list):
        raise SystemExit(f"cases 必须是列表：{path}")
    for case in cases:
        if not isinstance(case, dict) or "id" not in case:
            raise SystemExit(f"存在缺少 id 的用例：{path}")
        _check_scope_kinds(case)
    return cfg, digest


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
    trace_id = f"eval-{case['id']}"
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
                trace_id=f"{trace_id}-{index}",
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
                select(MemoryDecisionLog)
                .where(MemoryDecisionLog.run_id == run_id)
                .order_by(MemoryDecisionLog.created_at, MemoryDecisionLog.id)
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

    reasons = [log.reason or "" for log in logs]
    rejected = [
        {"reason": log.reason, "candidate": log.candidate or {}} for log in logs if log.reason
    ]
    rejected = [
        item for item in rejected if str(item["reason"]).startswith(REJECT_PREFIX)
    ]
    decision_actions = [
        log.action for log in logs if not str(log.reason or "").startswith(REJECT_PREFIX)
    ]
    return {
        "actions": [log.action for log in logs],
        "decision_actions": decision_actions,
        "reasons": reasons,
        "rejected": rejected,
        "logs": [
            {
                "action": log.action,
                "reason": log.reason,
                "memory_id": str(log.memory_id) if log.memory_id else None,
                "candidate": log.candidate or {},
            }
            for log in logs
        ],
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
                "valid_to": memory.valid_to.isoformat() if memory.valid_to else None,
            }
            for memory in written
        ],
        "pending": [
            {"id": str(memory.id), "type": memory.type, "slot_key": memory.slot_key}
            for memory in pending
        ],
        "run_status": run_row.status if run_row else "missing",
        "user_id": str(user_id),
        "trace_id": trace_id,
    }


def _score(cases: list[dict], results: list[dict | None]) -> dict:
    per_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    written_total = 0
    wrong_total = 0
    action_checked = 0
    action_correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    time_checked = 0
    time_correct = 0
    reject_checked = 0
    reject_correct = 0
    reject_by_category: dict[str, dict[str, int]] = defaultdict(
        lambda: {"checked": 0, "correct": 0}
    )
    write_by_category: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "written": 0}
    )
    failures: list[dict] = []
    errored_cases = 0

    for case, result in zip(cases, results, strict=False):
        case_id = str(case["id"])
        if result is None or result.get("error") or result.get("run_status") == "error":
            errored_cases += 1
            failures.append(
                {
                    "case_id": case_id,
                    "kind": "error",
                    "error": (result or {}).get("error")
                    or (result or {}).get("run_status")
                    or "missing_result",
                }
            )
            continue

        expected = case.get("expect") or []
        actual = result.get("written") or []
        written_total += len(actual)
        category = case.get("category")
        if category:
            write_by_category[str(category)]["cases"] += 1
            write_by_category[str(category)]["written"] += len(actual)
        used: set[int] = set()
        missing: list[dict] = []
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
                missing.append(want)
            else:
                used.add(matched)
                per_type[type_key]["tp"] += 1
        extra: list[dict] = []
        for index, memory in enumerate(actual):
            if index in used:
                continue
            per_type[memory["type"]]["fp"] += 1
            wrong_total += 1
            extra.append(
                {
                    "type": memory.get("type"),
                    "slot_key": memory.get("slot_key"),
                    "subject": memory.get("subject"),
                    "value": memory.get("value"),
                    "scope": memory.get("scope"),
                }
            )

        expected_action = case.get("expected_action")
        action_failure: dict | None = None
        if expected_action:
            action_checked += 1
            actual_action = (result.get("decision_actions") or ["NONE"])[0]
            confusion[expected_action][actual_action] += 1
            if actual_action == expected_action:
                action_correct += 1
            else:
                action_failure = {"expected": expected_action, "actual": actual_action}

        time_failure: dict | None = None
        check = case.get("check_time")
        if check:
            time_checked += 1
            if any(
                memory.get("slot_key") == check.get("slot_key")
                and memory.get("time") == check.get("time")
                for memory in actual
            ):
                time_correct += 1
            else:
                time_failure = {"expected": check}

        reject_failure: dict | None = None
        if case.get("expect_rejected"):
            reject_checked += 1
            category = str(case.get("reject_category") or "other")
            reject_by_category[category]["checked"] += 1
            prefix = str(case.get("reject_prefix") or REJECT_PREFIX)
            hit = any(str(reason).startswith(prefix) for reason in result.get("reasons") or [])
            if hit:
                reject_correct += 1
                reject_by_category[category]["correct"] += 1
            else:
                reject_failure = {
                    "category": category,
                    "expected_prefix": prefix,
                    "actual_reasons": result.get("reasons") or [],
                }

        if missing or extra or action_failure or time_failure or reject_failure:
            failure: dict = {"case_id": case_id, "kind": "mismatch"}
            if missing:
                failure["missing"] = missing
            if extra:
                failure["extra"] = extra
            if action_failure:
                failure["action"] = action_failure
            if time_failure:
                failure["time"] = time_failure
            if reject_failure:
                failure["reject"] = reject_failure
            failures.append(failure)

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
        "reject_accuracy": round(reject_correct / reject_checked, 4) if reject_checked else 0.0,
        "reject_accuracy_by_category": {
            key: {
                "checked": value["checked"],
                "correct": value["correct"],
                "accuracy": round(value["correct"] / value["checked"], 4)
                if value["checked"]
                else 0.0,
            }
            for key, value in reject_by_category.items()
        },
        "write_by_category": {
            key: dict(value) for key, value in write_by_category.items()
        },
        "counts": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "written_total": written_total,
            "wrong_total": wrong_total,
            "action_checked": action_checked,
            "action_correct": action_correct,
            "time_checked": time_checked,
            "time_correct": time_correct,
            "reject_checked": reject_checked,
            "reject_correct": reject_correct,
            "cases": len(results),
            "errored_cases": errored_cases,
        },
        "failures": failures,
        "cases": len(results),
    }


def _append_jsonl(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_raw(path: Path) -> list[dict]:
    entries: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _merge_entries(entries: list[dict]) -> list[dict]:
    """同一用例保留最后一条（重跑覆盖之前的异常记录）。"""
    latest: dict[str, dict] = {}
    for entry in entries:
        case_id = str(entry.get("case_id"))
        latest[case_id] = entry
    return sorted(latest.values(), key=lambda item: int(item.get("index", 0)))


def _results_for_cases(cases: list[dict], entries: list[dict]) -> list[dict | None]:
    by_id = {str(entry.get("case_id")): entry for entry in _merge_entries(entries)}
    return [by_id.get(str(case["id"])) for case in cases]


def _print_metrics(metrics: dict) -> None:
    print("\n汇总")
    for key in (
        "precision",
        "recall",
        "wrong_memory_rate",
        "action_accuracy",
        "time_accuracy",
        "reject_accuracy",
    ):
        print(f"  {key}: {metrics[key]}")
    print(f"  by_type: {metrics['by_type']}")
    print(f"  reject_accuracy_by_category: {metrics['reject_accuracy_by_category']}")
    print(f"  write_by_category: {metrics['write_by_category']}")
    print(f"  resolve_confusion: {metrics['resolve_confusion']}")
    print(f"  counts: {metrics['counts']}")
    print(f"  失败用例: {len(metrics['failures'])}")


async def main_async(
    args: argparse.Namespace,
    cases: list[dict],
    cfg: dict,
    digest: str,
    cases_path: Path,
    results_path: Path,
) -> int:
    settings = Settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    gateway = _build_gateway(settings, sessionmaker)
    embedder = build_embedding_service(settings)

    if args.resume:
        raw_path = Path(args.resume)
    elif args.raw:
        raw_path = Path(args.raw)
    else:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        raw_path = RUNS_DIR / f"{stamp}.jsonl"

    existing = _load_raw(raw_path) if args.resume and raw_path.exists() else []
    done = {
        str(entry.get("case_id")) for entry in existing if not entry.get("error")
    }

    meta = cfg["meta"]
    print(
        f"记忆评测：now={meta['now']} tz={meta['tz']} cases={len(cases)} "
        f"db={settings.database_url} raw={raw_path}"
    )
    processed = 0
    error_count = 0
    aborted = False
    abort_reason = ""
    for index, case in enumerate(cases):
        case_id = str(case["id"])
        if case_id in done:
            print(f"[SKIP] {case_id} 已完成")
            continue
        try:
            result = await _run_case(sessionmaker, gateway, embedder, settings, case, meta)
            status = "PASS" if not (case.get("expect") and not result["written"]) else "DONE"
            print(f"[{status}] {case_id} actions={result['actions']} written={len(result['written'])}")
        except Exception as exc:
            print(f"[FAIL] {case_id} 异常：{type(exc).__name__}: {exc}")
            result = {"error": f"{type(exc).__name__}: {exc}", "run_status": "error"}
        entry = {"case_id": case_id, "index": index, "error": result.get("error")}
        entry.update(result)
        _append_jsonl(raw_path, entry)

        processed += 1
        if result.get("error"):
            error_count += 1
        if processed >= 5 and error_count / processed > ABORT_ERROR_RATE:
            aborted = True
            abort_reason = (
                f"error 占比 {error_count}/{processed} 超过 {ABORT_ERROR_RATE:.0%}，已中止"
            )
            print(f"[ABORT] {abort_reason}；可用 --resume {raw_path} 续跑")
            break

    entries = _load_raw(raw_path) if raw_path.exists() else []
    if aborted or args.resume:
        entry_ids = {str(entry.get("case_id")) for entry in entries}
        scored_cases = [case for case in cases if str(case["id"]) in entry_ids]
    else:
        scored_cases = cases
    results = _results_for_cases(scored_cases, entries)
    metrics = _score(scored_cases, results)
    metrics["cases_planned"] = len(cases)
    metrics["cases_scored"] = len(scored_cases)
    if aborted:
        metrics["aborted"] = True
        metrics["aborted_reason"] = abort_reason
    eval_user_ids = [
        uuid.UUID(str(result["user_id"]))
        for result in results
        if result and result.get("user_id")
    ]
    async with sessionmaker() as session:
        model_rows = (
            await session.execute(
                select(LLMCall.alias, LLMCall.model_id)
                .where(LLMCall.user_id.in_(eval_user_ids))
                .distinct()
            )
        ).all() if eval_user_ids else []
    git_sha, dirty = _resolve_git_state(args.git_sha, args.git_dirty)
    metrics["models"] = [{"alias": alias, "model_id": model_id} for alias, model_id in model_rows]
    metrics["embedding_model"] = embedder.model_name
    metrics["extractor_version"] = EXTRACTOR_VERSION
    metrics["harness_version"] = HARNESS_VERSION
    metrics["case_file"] = cases_path.name
    metrics["case_file_sha256"] = digest
    metrics["git_sha"] = git_sha
    metrics["dirty"] = dirty
    metrics["raw_file"] = str(raw_path)
    metrics["ts"] = dt.datetime.now(dt.UTC).isoformat()

    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics, ensure_ascii=False) + "\n")

    _print_metrics(metrics)
    print(f"  结果已追加：{results_path}")
    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="记忆评测（真实模型，手动运行）")
    parser.add_argument(
        "--cases", default=str(PROJECT_ROOT / "tests" / "evals" / "memory_cases.yaml")
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--only", default=None, help="只跑指定用例 id，逗号分隔（如 s01,e01,i01）"
    )
    parser.add_argument(
        "--check-cases", action="store_true", help="只校验用例文件结构，不连库"
    )
    parser.add_argument("--raw", default=None, help="逐条原始输出路径（默认自动生成）")
    parser.add_argument("--resume", default=None, metavar="RAW", help="从已有原始输出文件续跑")
    parser.add_argument(
        "--results", default=str(RESULTS_PATH), help="指标追加文件（默认 tests/evals/results.jsonl）"
    )
    parser.add_argument("--git-sha", default=None, help="无 git 环境时显式指定提交 sha")
    parser.add_argument(
        "--git-dirty", action="store_true", help="配合 --git-sha 标记工作区有未提交改动"
    )
    parser.add_argument(
        "--score-from", default=None, metavar="RAW", help="只按已有原始输出重新计分"
    )
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cfg, digest = load_cases(cases_path)
    all_cases = cfg["cases"]
    cases = all_cases[: args.limit] if args.limit else all_cases
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if str(case["id"]) in wanted]
        found = {str(case["id"]) for case in cases}
        missing = wanted - found
        if missing:
            raise SystemExit(f"用例 id 不存在：{','.join(sorted(missing))}")

    if args.check_cases:
        print(f"用例文件校验通过：{cases_path} cases={len(all_cases)} sha256={digest[:12]}")
        return

    results_path = Path(args.results)
    if args.score_from:
        entries = _load_raw(Path(args.score_from))
        entry_ids = {str(entry.get("case_id")) for entry in entries}
        scored_cases = [case for case in cases if str(case["id"]) in entry_ids]
        results = _results_for_cases(scored_cases, entries)
        metrics = _score(scored_cases, results)
        metrics["cases_planned"] = len(cases)
        metrics["cases_scored"] = len(scored_cases)
        git_sha, dirty = _resolve_git_state(args.git_sha, args.git_dirty)
        metrics["extractor_version"] = EXTRACTOR_VERSION
        metrics["harness_version"] = HARNESS_VERSION
        metrics["case_file"] = cases_path.name
        metrics["case_file_sha256"] = digest
        metrics["git_sha"] = git_sha
        metrics["dirty"] = dirty
        metrics["raw_file"] = args.score_from
        _print_metrics(metrics)
        return

    _migrate()  # 同步执行，避免与 asyncio.run 嵌套
    sys.exit(asyncio.run(main_async(args, cases, cfg, digest, cases_path, results_path)))


if __name__ == "__main__":
    main()
