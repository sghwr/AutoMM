"""LLM provider 工厂。"""

from __future__ import annotations

from typing import Any

from .base import Invocation, LLMProvider, ProviderError
from .codex import CodexProvider
from .dsh import DshHeadlessProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "codex_exec": CodexProvider,
    "dsh_headless": DshHeadlessProvider,
}


def get_provider(config: dict[str, Any]) -> LLMProvider:
    name = str(config.get("provider", "codex_exec"))
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ProviderError(f"未知 LLM provider：{name}")
    return cls(config)


__all__ = ["Invocation", "LLMProvider", "ProviderError", "get_provider"]