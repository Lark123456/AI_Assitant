"""阶段 1 修订 2：FeishuAdapter 发送幂等 uuid 派生。"""

from app.adapters.feishu_adapter import feishu_send_uuid


def test_short_collapse_key_used_directly():
    assert feishu_send_uuid("reminder:abc") == "reminder:abc"


def test_long_collapse_key_hashed():
    key = f"reminder:{'x' * 36}:{'y' * 36}:0"  # 超过飞书 uuid 上限 64 字符
    derived = feishu_send_uuid(key)
    assert derived is not None
    assert len(derived) <= 64
    assert derived != key
    # 确定性：同一 key 得同一 uuid（重试投递才能被飞书去重）
    assert derived == feishu_send_uuid(key)


def test_none_when_no_collapse_key():
    """无 collapse_key（普通回复）不传 uuid，由飞书按请求去重。"""
    assert feishu_send_uuid(None) is None
    assert feishu_send_uuid("") is None
