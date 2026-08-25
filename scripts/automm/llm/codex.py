"""Codex CLI 后端：保留 0.0.2 的原始实现作为回归/降级后端。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..common import ROOT, read_json, resolve_project_path
from .base import Invocation, LLMProvider, ProviderError


class CodexProvider(LLMProvider):
    backend = "codex_exec"

    def _executable(self) -> str:
        executable = shutil.which(str(self.config.get("executable", "codex")))
        if not executable:
            raise ProviderError("找不到 Codex CLI")
        return executable

    def probe(self) -> dict[str, Any]:
        executable = self._executable()
        result = subprocess.run(
            [executable, "exec", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False,
        )
        help_text = result.stdout + result.stderr
        missing = [item for item in self.config.get("required_capabilities", []) if item not in help_text]
        if result.returncode != 0 or missing:
            raise ProviderError(f"Codex CLI 能力探测失败，缺少：{missing}")
        return {"executable": executable, "capabilities": self.config.get("required_capabilities", [])}

    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        schema_path = resolve_project_path(self.config["output_schema"], must_exist=True)
        command = [
            self._executable(), "exec", "-", "-C", str(ROOT),
            "--output-schema", str(schema_path),
            "--output-last-message", str(output_path),
            "--json", "--color", "never",
        ]
        sandbox = str(self.config.get("sandbox", "workspace-write"))
        if self.config.get("automatic_approval", True):
            if sandbox != "workspace-write":
                raise ProviderError("automatic_approval 只允许 workspace-write sandbox")
            command.append("--approve-for-me")
        else:
            command.extend(["--sandbox", sandbox])
        if self.config.get("skip_git_repo_check", True):
            command.append("--skip-git-repo-check")
        if self.config.get("ephemeral"):
            command.append("--ephemeral")
        if self.config.get("model"):
            command.extend(["--model", str(self.config["model"])])
        return Invocation(command=command, stdin=prompt, output_path=output_path)

    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        if returncode != 0:
            raise ProviderError(f"Codex Agent 退出码 {returncode}，详见 stderr")
        output_path = invocation.output_path
        if output_path is None or not output_path.exists():
            raise ProviderError("Agent 未生成 response.json")
        return read_json(output_path)