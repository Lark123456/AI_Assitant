"""抽取提示词：few-shot 与评测用例分离维护，避免评测集泄漏进提示词。"""

from pathlib import Path

from app.memory.extract import (
    EXTRACTOR_VERSION,
    FEW_SHOT_NEGATIVE,
    FEW_SHOT_POSITIVE,
    build_system_prompt,
)

CASES_PATH = Path(__file__).resolve().parents[1] / "evals" / "memory_cases.yaml"


def test_extractor_version_is_v2() -> None:
    assert EXTRACTOR_VERSION == "memory-extract-v2"


def test_few_shot_counts() -> None:
    assert len(FEW_SHOT_POSITIVE) == 6
    assert len(FEW_SHOT_NEGATIVE) == 8


def test_few_shot_text_does_not_appear_in_eval_cases() -> None:
    cases = CASES_PATH.read_text(encoding="utf-8")
    for text in (*FEW_SHOT_POSITIVE, *FEW_SHOT_NEGATIVE):
        assert text not in cases, f"few-shot 文本出现在评测用例中：{text}"


def test_system_prompt_contains_rules_and_examples() -> None:
    prompt = build_system_prompt()
    assert "episode 必须有明确日期锚点" in prompt
    for text in (*FEW_SHOT_POSITIVE, *FEW_SHOT_NEGATIVE):
        assert text in prompt
