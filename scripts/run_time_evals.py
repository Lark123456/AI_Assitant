"""时间表达评测（手动运行，真实模型 + 本地 Postgres，不进 CI）。

用法：
    make up && make migrate
    uv run python scripts/run_time_evals.py [--cases PATH] [--limit N]

评测逻辑：固定当前时间与时区（yaml meta），逐条把话语喂给真实 Friday，
检查 trigger_instance 里创建的 reminder 的 fire_at 是否与期望一致；
expect_reminder=false 的话语则要求不产生任何提醒。
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.console_adapter import ConsoleAdapter  # noqa: E402
from app.adapters.identity import make_identity_resolver  # noqa: E402
from app.core.clock import FakeClock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.db.base import make_engine, make_sessionmaker  # noqa: E402
from app.db.models import TriggerInstance  # noqa: E402
from app.engine.pipeline import InboundPipeline  # noqa: E402
from app.llm.gateway import LLMGateway  # noqa: E402
from app.llm.providers.openai_compat import OpenAICompatProvider  # noqa: E402


async def run_case(pipeline: InboundPipeline, case: dict, run_id: str) -> tuple[bool, str]:
    """跑一条话语，返回 (是否通过, 说明)。每条 case 用独立用户，避免相互干扰。"""
    from app.adapters.base import InboundEvent
    from app.db.models import ChannelIdentity

    external_id = f"eval-{run_id}-{case['id']}"
    await pipeline.handle(
        InboundEvent(
            channel="console",
            external_user_id=external_id,
            kind="message",
            text=case["utterance"],
            idempotency_key=f"eval-{run_id}-{case['id']}",
        )
    )

    sessionmaker = pipeline._sessionmaker  # noqa: SLF001 — 评测脚本直接取内部工厂
    async with sessionmaker() as session:
        identity = (
            await session.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == "console",
                    ChannelIdentity.external_id == external_id,
                )
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(TriggerInstance).where(TriggerInstance.user_id == identity.user_id)
            )
        ).scalars().all()

    expect_reminder = case.get("expect_reminder", True)
    if not expect_reminder:
        if rows:
            return False, f"不应建提醒，实际建了 {len(rows)} 条（fire_at={[r.fire_at.isoformat() for r in rows]}）"
        return True, "正确未建提醒"

    if len(rows) != 1:
        return False, f"应恰好建 1 条提醒，实际 {len(rows)} 条"
    expected = dt.datetime.fromisoformat(case["expected_fire_at"])
    actual = rows[0].fire_at
    if actual != expected:
        return False, f"期望 {expected.isoformat()}，实际 {actual.isoformat()}"
    return True, actual.isoformat()


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    cfg = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    meta = cfg["meta"]
    cases = cfg["cases"][: args.limit] if args.limit else cfg["cases"]

    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    gateway = LLMGateway(
        aliases_path=settings.aliases_path,
        providers={
            "openai_compat": OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key),
            "openai_compat_agent": OpenAICompatProvider(
                settings.llm_agent_base_url, settings.llm_agent_api_key
            ),
        },
        sessionmaker=sessionmaker,
        clock=FakeClock(dt.datetime.fromisoformat(meta["now"])),
        daily_limit=settings.llm_daily_limit,
    )
    pipeline = InboundPipeline(
        sessionmaker=sessionmaker,
        clock=FakeClock(dt.datetime.fromisoformat(meta["now"])),
        settings=settings,
        gateway=gateway,
        adapters={"console": ConsoleAdapter(make_identity_resolver(sessionmaker, "console"))},
    )

    run_id = uuid.uuid4().hex[:8]
    print(f"评测运行 {run_id}：now={meta['now']} tz={meta['tz']} cases={len(cases)}")
    passed = 0
    for case in cases:
        try:
            ok, detail = await run_case(pipeline, case, run_id)
        except Exception as exc:  # noqa: BLE001 — 评测脚本需逐条容错
            ok, detail = False, f"异常：{type(exc).__name__}: {exc}"
        mark = "PASS" if ok else "FAIL"
        try:
            print(f"[{mark}] {case['id']} {case['utterance']} -> {detail}")
        except UnicodeEncodeError:  # Windows 控制台编码兜底
            print(f"[{mark}] {case['id']} -> {detail.encode('ascii', 'backslashreplace').decode()}")
        passed += int(ok)
    print(f"合计：{passed}/{len(cases)} 通过")
    await engine.dispose()
    return 0 if passed == len(cases) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="时间表达评测（真实模型）")
    parser.add_argument(
        "--cases", default=str(PROJECT_ROOT / "tests" / "evals" / "time_expressions.yaml")
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
