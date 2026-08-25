"""适配器工厂以及任务状态文件的远端生命周期桥接。"""

from __future__ import annotations

from typing import Any

from ..common import RUNTIME_DIR, read_json, utc_now, write_json
from .base import REMOTE_TERMINAL, RemoteAdapter
from .kaggle import KaggleAdapter
from .ssh import SSHAdapter


def get_adapter(backend: str) -> RemoteAdapter:
    if backend == "ssh":
        return SSHAdapter()
    if backend == "kaggle":
        return KaggleAdapter()
    raise ValueError(f"未知远端后端: {backend}")


def _paths(task_id: str) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    directory = RUNTIME_DIR / "tasks" / task_id
    spec = read_json(directory / "task.json")
    state = read_json(directory / "status.json")
    return directory, directory / "status.json", spec, state


def _save(directory: Any, path: Any, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = utc_now()
    write_json(path, state)
    write_json(directory / f"attempt-{int(state.get('attempt', 1)):03d}-status.json", state)
    return state


def submit_remote(task_id: str) -> dict[str, Any]:
    directory, path, spec, state = _paths(task_id)
    if state.get("status") != "queued":
        return state
    adapter = get_adapter(str(spec["backend"]))
    try:
        remote = adapter.submit(spec)
        state.update(remote)
        state.update(
            {
                "status": remote.get("status", "running"),
                "started_at": utc_now(),
                "last_remote_poll_at": utc_now(),
            }
        )
    except Exception as exc:
        state.update(
            {
                "status": "failed",
                "failure_type": "remote_submit",
                "message": str(exc),
                "finished_at": utc_now(),
            }
        )
    return _save(directory, path, state)


def reconcile_remote(task_id: str) -> dict[str, Any] | None:
    directory, path, spec, state = _paths(task_id)
    if state.get("status") not in {"queued", "running"}:
        return None
    adapter = get_adapter(str(spec["backend"]))
    try:
        remote = adapter.status(spec, state)
        state.update(remote)
        state["last_remote_poll_at"] = utc_now()
        if state.get("status") in REMOTE_TERMINAL:
            state["finished_at"] = state.get("finished_at") or utc_now()
            if state["status"] == "succeeded":
                pulled = adapter.pull(spec, state)
                state.update({"artifacts_pulled": True, **pulled})
    except Exception as exc:
        state.update(
            {
                "status": "failed",
                "failure_type": "remote_poll_or_pull",
                "message": str(exc),
                "finished_at": utc_now(),
            }
        )
    return _save(directory, path, state)
