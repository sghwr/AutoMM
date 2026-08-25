"""共享的路径、配置、哈希和原子文件操作。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("AUTOMM_ROOT", Path(__file__).resolve().parents[2])).resolve()
CONFIG_DIR = ROOT / "config"
RUNTIME_DIR = ROOT / "runtime"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return ({} if default is None else default) if value is None else value


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无法解析: {path.relative_to(ROOT)}: {exc}") from exc


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_yaml(path: Path, value: Any) -> None:
    _atomic_write(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))


def write_text(path: Path, value: str) -> None:
    _atomic_write(path, value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def effective_config(
    problem_id: str | None = None,
    question_id: str | None = None,
    task_config: Path | None = None,
    cli_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按默认 < 项目 < 题目 < 小问 < 任务 < CLI 合并配置。"""
    result: dict[str, Any] = {}
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        result[path.stem] = read_yaml(path)
    if problem_id:
        result = deep_merge(result, read_yaml(ROOT / "problems" / problem_id / "config.yaml"))
    if problem_id and question_id:
        result = deep_merge(
            result,
            read_yaml(ROOT / "problems" / problem_id / question_id / "config.yaml"),
        )
    if task_config:
        result = deep_merge(result, read_yaml(resolve_project_path(task_config)))
    if cli_override:
        result = deep_merge(result, cli_override)
    return result


def config_section(
    section: str,
    problem_id: str | None = None,
    question_id: str | None = None,
    task_config: Path | None = None,
    cli_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回经过分层合并后的单个配置段。"""
    value = effective_config(problem_id, question_id, task_config, cli_override).get(section, {})
    if not isinstance(value, dict):
        raise ValueError(f"有效配置段 {section} 必须是映射")
    return value


def resolve_project_path(path: str | Path, *, must_exist: bool = False) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (ROOT / candidate).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"路径必须位于项目内: {path}")
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"路径不存在: {resolved.relative_to(ROOT)}")
    return resolved


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def hash_path(path: str | Path | None) -> str:
    if not path:
        return hashlib.sha256(b"").hexdigest()
    resolved = resolve_project_path(path, must_exist=True)
    digest = hashlib.sha256()
    if resolved.is_file():
        digest.update(relative(resolved).encode("utf-8"))
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    ignored_dirs = {"__pycache__", ".ruff_cache", ".venv"}
    for item in sorted(
        p
        for p in resolved.rglob("*")
        if p.is_file() and not ignored_dirs.intersection(p.parts) and p.suffix.lower() != ".pyc"
    ):
        digest.update(relative(item).encode("utf-8"))
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


class FileLock:
    def __init__(self, path: Path, stale_after_seconds: int) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds

    def acquire(self, owner: str) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"owner": owner, "pid": os.getpid(), "created_at": utc_now()})
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        return True

    def info(self) -> dict[str, Any]:
        return read_json(self.path) if self.path.exists() else {}

    def is_stale(self) -> bool:
        if not self.path.exists():
            return False
        age = datetime.now(timezone.utc).timestamp() - self.path.stat().st_mtime
        return age > self.stale_after_seconds

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()
