"""阶段 1 修订 2：Console 路由由 ENABLE_CONSOLE 控制，默认关闭。

说明：本项目所用 FastAPI 版本把 include_router 的路由包成 _IncludedRouter，
不能通过 route.path 平铺探查，这里用 TestClient 实际探测路由行为。
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.config import get_settings


class _StubPipeline:
    async def ingest(self, event):
        return SimpleNamespace(created=True)

    async def process(self, ingested):
        pass


def _client() -> TestClient:
    from app.main import create_app

    app = create_app()
    app.state.pipeline = _StubPipeline()
    # 不进 with（不触发 lifespan/启动补处理），路由测试不需要 DB
    return TestClient(app)


def test_console_router_disabled_by_default(monkeypatch):
    """未设置 ENABLE_CONSOLE 时：路由不存在（404）。"""
    monkeypatch.delenv("ENABLE_CONSOLE", raising=False)
    get_settings.cache_clear()
    try:
        resp = _client().post(
            "/console/messages", json={"external_user_id": "u1", "text": "你好"}
        )
        assert resp.status_code == 404
    finally:
        get_settings.cache_clear()


def test_console_router_enabled_when_configured(monkeypatch):
    """ENABLE_CONSOLE=1 时：路由可用（pipeline 换成桩，不触真实 LLM/DB）。"""
    monkeypatch.setenv("ENABLE_CONSOLE", "1")
    get_settings.cache_clear()
    try:
        resp = _client().post(
            "/console/messages", json={"external_user_id": "u1", "text": "你好"}
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"
    finally:
        get_settings.cache_clear()
