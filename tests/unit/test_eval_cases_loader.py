"""评测用例加载器：scope_kind 必须是字符串（YAML 会把裸 on 解析成布尔）。"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "run_memory_evals.py"

_BASE = """
meta:
  now: "2026-11-06T10:00:00+08:00"
  tz: Asia/Shanghai
cases:
  - id: loader01
    text: "今天加班到九点"
    expect:
      - type: episode
        scope_kind: {kind}
"""


def _run_check(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-cases", "--cases", str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_check_cases_rejects_bool_scope_kind(tmp_path: Path) -> None:
    bad = tmp_path / "cases_bool.yaml"
    bad.write_text(_BASE.format(kind="on"), encoding="utf-8")
    done = _run_check(bad)
    assert done.returncode != 0
    assert "scope_kind" in done.stdout + done.stderr


def test_check_cases_accepts_quoted_scope_kind(tmp_path: Path) -> None:
    good = tmp_path / "cases_ok.yaml"
    good.write_text(_BASE.format(kind="'on'"), encoding="utf-8")
    done = _run_check(good)
    assert done.returncode == 0
    assert "校验通过" in done.stdout
