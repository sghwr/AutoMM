"""受控的可恢复清理：只移动允许类型到项目内 .trash。"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ROOT, append_jsonl, config_section, hash_path, relative, resolve_project_path, utc_now


def move_to_trash(path: str, kind: str, reason: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "MOVE_TO_TRASH":
        raise ValueError("必须显式提供确认词 MOVE_TO_TRASH")
    config = config_section("compute")
    allowed = set(config.get("cleanup", {}).get("allowed_kinds", []))
    if kind not in allowed:
        raise ValueError(f"清理类型不在白名单：{kind}")
    if not reason.strip():
        raise ValueError("清理必须说明理由")
    source = resolve_project_path(path, must_exist=True)
    protected = {ROOT, ROOT / "config", ROOT / "scripts", ROOT / "request", ROOT / "problems", ROOT / "knowledge"}
    if source in protected:
        raise ValueError("禁止清理项目根目录或核心目录")
    trash_root = ROOT / ".trash"
    if source == trash_root or trash_root in source.parents:
        raise ValueError("目标已经位于 .trash")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = trash_root / timestamp / Path(relative(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"回收目标已存在：{relative(destination)}")
    fingerprint = hash_path(source)
    shutil.move(str(source), str(destination))
    record = {
        "at": utc_now(),
        "action": "move_to_trash",
        "kind": kind,
        "reason": reason,
        "source": relative(source),
        "destination": relative(destination),
        "fingerprint_sha256": fingerprint,
        "recoverable": True,
    }
    append_jsonl(trash_root / "cleanup.jsonl", record)
    return record


def list_trash() -> list[dict[str, Any]]:
    root = ROOT / ".trash"
    if not root.exists():
        return []
    return [
        {"path": relative(path), "bytes": path.stat().st_size} for path in sorted(root.rglob("*")) if path.is_file()
    ]
