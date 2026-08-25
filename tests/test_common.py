from __future__ import annotations

import os
from pathlib import Path

import pytest
from automm.common import FileLock, deep_merge, hash_json, hash_path, resolve_project_path

pytestmark = pytest.mark.unit


def test_deep_merge_preserves_unrelated_nested_values() -> None:
    result = deep_merge({"a": {"x": 1, "y": 2}, "b": 3}, {"a": {"x": 9}, "c": 4})
    assert result == {"a": {"x": 9, "y": 2}, "b": 3, "c": 4}


def test_hash_json_is_order_independent() -> None:
    assert hash_json({"a": 1, "b": 2}) == hash_json({"b": 2, "a": 1})


def test_hash_path_changes_with_content(project_root: Path) -> None:
    path = project_root / "data" / "sample.txt"
    path.write_text("first", encoding="utf-8")
    before = hash_path(path)
    path.write_text("second", encoding="utf-8")
    assert hash_path(path) != before


def test_resolve_project_path_rejects_escape(project_root: Path) -> None:
    assert resolve_project_path("data").is_relative_to(project_root)
    with pytest.raises(ValueError, match="项目内"):
        resolve_project_path(project_root.parent / "outside.txt")


def test_file_lock_is_exclusive_and_releasable(project_root: Path) -> None:
    path = project_root / "runtime" / "locks" / "test.lock"
    first = FileLock(path, stale_after_seconds=60)
    second = FileLock(path, stale_after_seconds=60)
    assert first.acquire("first") is True
    assert second.acquire("second") is False
    assert first.info()["owner"] == "first"
    first.release()
    assert second.acquire("second") is True
    second.release()


def test_file_lock_detects_stale_mtime(project_root: Path) -> None:
    path = project_root / "runtime" / "locks" / "stale.lock"
    lock = FileLock(path, stale_after_seconds=1)
    assert lock.acquire("owner")
    old = path.stat().st_mtime - 5
    os.utime(path, (old, old))
    assert lock.is_stale() is True
    lock.release()


def test_atomic_write_retries_transient_windows_permission_error(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from automm import common

    original_replace = common.os.replace
    calls = {"count": 0}

    def flaky_replace(source: str | bytes, target: str | bytes) -> None:
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("transient lock")
        original_replace(source, target)

    monkeypatch.setattr(common.os, "replace", flaky_replace)
    common.write_text(project_root / "retry.txt", "ok")
    assert (project_root / "retry.txt").read_text(encoding="utf-8") == "ok"
    assert calls["count"] == 3
