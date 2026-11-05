"""aliases.yaml 加载与校验。"""

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class AliasConfig:
    """单个档位别名的配置。"""

    provider: str
    model: str
    params: dict
    fallback: str | None = None


def load_aliases(path: str) -> dict[str, AliasConfig]:
    """读取并校验别名配置。"""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"aliases file {path} is empty or malformed")
    aliases: dict[str, AliasConfig] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict) or "provider" not in cfg or "model" not in cfg:
            raise ValueError(f"alias {name} must define provider and model")
        aliases[name] = AliasConfig(
            provider=cfg["provider"],
            model=cfg["model"],
            params=cfg.get("params") or {},
            fallback=cfg.get("fallback"),
        )
    return aliases
