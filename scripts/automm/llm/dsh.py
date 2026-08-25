"""DSH headless 后端：`dsh --profile headless "<task>"` 一次性会话。

DSH 契约（0.1.1-rc.2，已核实）：
- 任务文本是唯一的位置参数（`[task...]`，多个词用空格连接），无 --model/--workspace/--cd；
- 调用目录即 workspace 根，自动加载该目录的 AGENTS.md；
- 默认模型来自 $DSH_HOME/settings.yaml（agent-default-model），无 CLI 覆盖；
- 工具呈现由 DSH_TOOLS_MODE 环境变量决定（native|code|both）；
- 进程把最后一条非空 assistant 文本写 stdout 后退出；turn/end 为 completed 时退出码 0，
  否则退出码 1，错误以 `dsh: <code>: <message>` 写 stderr。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import Invocation, LLMProvider, ProviderError


class DshHeadlessProvider(LLMProvider):
    backend = "dsh_headless"

    def _executable(self) -> str:
        executable = shutil.which(str(self.config.get("executable", "dsh")))
        if not executable:
            raise ProviderError("找不到 dsh CLI（请先安装 @deepseek-ai/dsh）")
        return executable

    def probe(self) -> dict[str, Any]:
        executable = self._executable()
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False,
        )
        if result.returncode != 0:
            raise ProviderError(f"dsh 探测失败：{(result.stderr or result.stdout).strip()[-500:]}")
        version = (result.stdout + result.stderr).strip().splitlines()[:1]
        return {"executable": executable, "version": version}

    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        profile = str(self.config.get("profile", "headless"))
        command = [self._executable(), "--profile", profile, prompt]
        env = dict(os.environ)
        env.setdefault("DSH_TOOLS_MODE", str(self.config.get("tools_mode", "native")))
        return Invocation(command=command, stdin=None, env=env, output_path=output_path)

    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        if returncode != 0:
            detail = (stderr or stdout).strip()[-2000:]
            raise ProviderError(f"dsh headless 退出码 {returncode}：{detail}")
        text = (stdout or "").strip()
        if not text:
            raise ProviderError("dsh headless 未产生最终响应文本")
        return _parse_json_text(text)


def _parse_json_text(text: str) -> dict[str, Any]:
    """从 LLM 最终文本中稳健提取 JSON 对象。"""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"无法解析 Agent JSON 响应：{exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("Agent 响应不是 JSON 对象")
    return value