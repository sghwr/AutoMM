"""远端适配器的公共契约和安全命令执行工具。"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

REMOTE_TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "lost"}


class AdapterError(RuntimeError):
    """远端平台调用失败，异常文本不得包含凭据。"""


def secret_value(config: dict[str, Any], value_key: str, env_key: str) -> str:
    """环境变量优先，配置明文字段作为显式 fallback。"""
    env_name = str(config.get(env_key, "") or "").strip()
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    return str(config.get(value_key, "") or "")


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """无 shell 执行外部命令，并将错误限制为非敏感输出。"""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError(f"命令执行失败: {Path(command[0]).name}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise AdapterError(f"{Path(command[0]).name} 返回 {result.returncode}: {detail}")
    return result


class RemoteAdapter(ABC):
    """计算后端统一生命周期。"""

    backend: str

    @abstractmethod
    def probe(self) -> dict[str, Any]:
        """执行只读连接和依赖检查。"""

    @abstractmethod
    def submit(self, spec: dict[str, Any]) -> dict[str, Any]:
        """幂等上传任务并启动，返回远端 job 标识。"""

    @abstractmethod
    def status(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """查询远端真实状态。"""

    @abstractmethod
    def pull(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """拉回日志、状态和结果，校验后写入本地输出目录。"""

    @abstractmethod
    def cancel(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """终止仍在运行的远端任务。"""
