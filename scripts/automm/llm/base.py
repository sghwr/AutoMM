"""LLM Provider 抽象：把 Agent 调用从具体 CLI 后端解耦。

AutoMM 0.0.4 起，模型调用不再硬编码 Codex CLI，而是通过 Provider 工厂选择后端。
后端职责：
- probe：探测可执行文件与必需能力；
- prepare：把 prompt 转成一次可执行调用（命令 + stdin + 环境 + 结构化输出位置）；
- extract_response：从运行产物提取并解析 JSON 响应。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    """LLM 后端探测或调用失败（映射为 agent_transport）。"""


@dataclass
class Invocation:
    """一次 provider 调用的完整构造。"""

    command: list[str]
    stdin: str | None = None
    env: dict[str, str] | None = None
    output_path: Path | None = None  # 后端若支持结构化输出文件则填写


class LLMProvider(ABC):
    backend: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def probe(self) -> dict[str, Any]:
        """探测可执行文件与必需能力；失败抛 ProviderError。"""

    @abstractmethod
    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        """构造一次调用；output_path 为后端结构化输出文件的期望位置。"""

    @abstractmethod
    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        """从运行产物提取并解析 JSON 响应；失败抛 ProviderError。"""