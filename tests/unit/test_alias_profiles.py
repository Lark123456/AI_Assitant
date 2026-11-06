"""Agent 套餐接入：jarvis_deep 走 agent 凭据组，其余档位保持默认。"""

from app.core.config import Settings
from app.llm.aliases import load_aliases


def test_jarvis_deep_uses_agent_profile() -> None:
    aliases = load_aliases("app/llm/aliases.yaml")
    # Jarvis 深档走 Agent Plan 端点，模型跟随控制台切换
    assert aliases["jarvis_deep"].provider == "openai_compat_agent"
    assert aliases["jarvis_deep"].model == "ark-code-latest"
    # 视觉档保持 Coding 套餐的豆包多模态模型（Agent 套餐模型为纯文本）
    assert aliases["vision_extract"].provider == "openai_compat"
    # Friday 全系仍在 Coding 套餐
    assert aliases["friday_fast"].provider == "openai_compat"
    assert aliases["memory_extract"].provider == "openai_compat"
    assert aliases["mini_plan"].provider == "openai_compat"


def test_settings_pick_up_agent_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_AGENT_BASE_URL", "https://agent.example.test/v3")
    monkeypatch.setenv("LLM_AGENT_API_KEY", "agent-key-for-test")
    settings = Settings(_env_file=None)
    assert settings.llm_agent_base_url == "https://agent.example.test/v3"
    assert settings.llm_agent_api_key == "agent-key-for-test"
