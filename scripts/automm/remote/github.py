"""独立工作区内的 GitHub 代码与结果中转。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..common import ROOT, RUNTIME_DIR, read_yaml, resolve_project_path, write_yaml
from .base import AdapterError, run_command

SECRET_KEYS = {"password", "auth_token", "smtp_auth_code", "authorization_code", "api_key", "token"}


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("" if str(key).lower() in SECRET_KEYS else redact_secrets(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


class GitHubRelayAdapter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        compute = read_yaml(ROOT / "config" / "compute.yaml")
        self.config = config or compute.get("github_relay", {})
        if not self.config.get("enabled", False):
            raise AdapterError("GitHub 中转未启用")
        self.repository = str(self.config.get("repository", "")).strip()
        self.branch = str(self.config.get("branch", "main")).strip()
        if not self.repository or not self.branch:
            raise AdapterError("GitHub repository 和 branch 不能为空")
        self.worktree = RUNTIME_DIR / "github_relay" / "worktree"

    def _git(self, args: list[str], *, cwd: Path | None = None, timeout: int = 60, check: bool = True):
        """在无所有权元数据的文件系统上显式声明 Git 安全目录。"""
        command = ["git", "-c", "safe.directory=*", *args]
        return run_command(command, cwd=cwd, timeout=timeout, check=check)

    def probe(self) -> dict[str, Any]:
        result = run_command(["git", "-c", "safe.directory=*", "ls-remote", "--heads", self.repository, self.branch], timeout=45)
        return {
            "backend": "github",
            "status": "ok",
            "repository_accessible": True,
            "branch_exists": bool(result.stdout.strip()),
        }

    def _ensure_worktree(self) -> None:
        if (self.worktree / ".git").is_dir():
            self._git(["remote", "set-url", "origin", self.repository], cwd=self.worktree)
            return
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        if self.worktree.exists() and any(self.worktree.iterdir()):
            raise AdapterError("GitHub 中转工作区存在但不是 Git 仓库")
        run_command(["git", "-c", "safe.directory=*", "clone", self.repository, str(self.worktree)], timeout=120)

    def _copy_for_push(self, path: str) -> str:
        source = resolve_project_path(path, must_exist=True)
        relative = source.relative_to(ROOT)
        target = self.worktree / relative
        if source.is_dir():
            ignored = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".ruff_cache")
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignored)
            for yaml_path in target.rglob("*.yaml"):
                if "config" in yaml_path.relative_to(self.worktree).parts:
                    write_yaml(yaml_path, redact_secrets(read_yaml(yaml_path)))
        elif source.suffix.lower() in {".yaml", ".yml"} and "config" in relative.parts:
            write_yaml(target, redact_secrets(read_yaml(source)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return relative.as_posix()

    def push(self, paths: list[str] | None = None, message: str = "AutoMM relay update") -> dict[str, Any]:
        self._ensure_worktree()
        self._git(["checkout", "-B", self.branch], cwd=self.worktree)
        selected = paths or list(self.config.get("push_paths", []))
        if not selected:
            raise AdapterError("GitHub push_paths 不能为空")
        staged = [self._copy_for_push(path) for path in selected]
        self._git(["add", "--", *staged], cwd=self.worktree)
        changed = self._git(["diff", "--cached", "--quiet"], cwd=self.worktree, check=False).returncode != 0
        if not changed:
            return {"status": "unchanged", "paths": staged}
        self._git(["config", "user.name", "AutoMM Relay"], cwd=self.worktree)
        self._git(["config", "user.email", "automm-relay@localhost"], cwd=self.worktree)
        self._git(["commit", "-m", message], cwd=self.worktree, timeout=60)
        self._git(["push", "origin", f"HEAD:{self.branch}"], cwd=self.worktree, timeout=180)
        commit = self._git(["rev-parse", "HEAD"], cwd=self.worktree).stdout.strip()
        return {"status": "pushed", "paths": staged, "commit": commit}

    def pull(self, paths: list[str] | None = None) -> dict[str, Any]:
        self._ensure_worktree()
        self._git(["fetch", "origin", self.branch], cwd=self.worktree, timeout=120)
        self._git(["checkout", "-B", self.branch, f"origin/{self.branch}"], cwd=self.worktree)
        selected = paths or list(self.config.get("pull_paths", []))
        copied: list[str] = []
        for path in selected:
            relative = Path(path)
            source = (self.worktree / relative).resolve()
            if self.worktree.resolve() not in source.parents or not source.exists():
                continue
            target = resolve_project_path(relative)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            copied.append(relative.as_posix())
        return {"status": "pulled", "paths": copied}
