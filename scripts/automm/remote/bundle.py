"""把本地任务转换为 SSH/Kaggle 都可执行的自包含目录。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..common import ROOT, RUNTIME_DIR, resolve_project_path, write_json, write_text

RUNNER_SOURCE = r"""from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE / "workspace"
STATUS = HERE / "remote-status.json"

def now():
    return datetime.now(timezone.utc).isoformat()

def write_status(value):
    value["updated_at"] = now()
    temp = STATUS.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, STATUS)

def main():
    spec = json.loads((HERE / "remote-task.json").read_text(encoding="utf-8"))
    state = {"task_id": spec["task_id"], "attempt": spec["attempt"], "status": "running", "started_at": now()}
    write_status(state)
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(10):
            state["heartbeat_at"] = now()
            write_status(state)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    output = WORKSPACE / spec["output_directory"]
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"AUTOMM_TASK_ID": spec["task_id"], "AUTOMM_OUTPUT_DIR": str(output)})
    if spec.get("seed") is not None:
        env.update({"AUTOMM_SEED": str(spec["seed"]), "PYTHONHASHSEED": str(spec["seed"])})
    command = [sys.executable, *spec["command"][1:]]
    # 强制把 --output 指向 runner 计算的绝对输出目录，消除 CLI 相对路径按 cwd 错写的问题。
    if "--output" in command:
        output_index = command.index("--output")
        if output_index + 1 < len(command):
            command[output_index + 1] = str(output)
    for index, item in enumerate(command):
        if item.startswith("--output="):
            command[index] = f"--output={output}"
    try:
        stdout_file = (HERE / "stdout.log").open("w", encoding="utf-8")
        stderr_file = (HERE / "stderr.log").open("w", encoding="utf-8")
        with stdout_file as out, stderr_file as err:
            process = subprocess.run(command, cwd=WORKSPACE / spec["working_directory"], env=env,
                                     stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                     timeout=int(spec.get("timeout_seconds") or 0) or None, check=False)
        state.update({"status": "succeeded" if process.returncode == 0 else "failed",
                      "returncode": process.returncode,
                      "failure_type": None if process.returncode == 0 else "process_exit"})
        if state["status"] == "succeeded":
            output_files = [path for path in output.rglob("*") if path.is_file()]
            if not output_files:
                state.update({
                    "status": "failed",
                    "failure_type": "empty_output",
                    "message": "进程返回 0 但输出目录为空，禁止判定成功",
                })
    except subprocess.TimeoutExpired:
        state.update({"status": "timed_out", "failure_type": "timeout", "message": "任务超过 timeout_seconds"})
    except Exception as exc:
        (HERE / "runner-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        state.update({"status": "failed", "failure_type": "remote_worker_error", "message": str(exc)})
    finally:
        stop.set()
        state["finished_at"] = now()
        write_status(state)
        with zipfile.ZipFile(HERE / "automm-result.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in output.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(output).as_posix())
        write_status(state)
    return 0 if state["status"] == "succeeded" else 1

if __name__ == "__main__":
    raise SystemExit(main())
"""


def _copy_source(source: Path, workspace: Path) -> None:
    target = workspace / source.relative_to(ROOT)
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ruff_cache", ".venv"),
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _portable_command(command: list[str]) -> list[str]:
    result = ["python3"]
    for item in command[1:]:
        path = Path(str(item))
        if path.is_absolute():
            try:
                result.append(path.resolve().relative_to(ROOT).as_posix())
                continue
            except ValueError:
                pass
        result.append(str(item).replace("\\", "/"))
    return result


def prepare_bundle(spec: dict[str, Any]) -> Path:
    """生成 attempt 唯一的可重复任务包；不读取输出目录中的旧结果。"""
    attempt = int(spec.get("attempt", 1))
    bundle = RUNTIME_DIR / "remote_bundles" / spec["task_id"] / f"attempt-{attempt:03d}"
    workspace = bundle / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    sources = {
        resolve_project_path(spec["code_path"], must_exist=True),
        resolve_project_path(spec["config_path"], must_exist=True),
        resolve_project_path(spec["input_path"], must_exist=True),
    }
    for source in sorted(sources, key=lambda value: value.as_posix()):
        _copy_source(source, workspace)
    portable = {
        **spec,
        "command": _portable_command([str(value) for value in spec["command"]]),
        "working_directory": str(spec["working_directory"]).replace("\\", "/"),
        "output_directory": str(spec["output_directory"]).replace("\\", "/"),
    }
    write_json(bundle / "remote-task.json", portable)
    write_text(bundle / "runner.py", RUNNER_SOURCE)
    manifest = {
        "task_id": spec["task_id"],
        "attempt": attempt,
        "sources": sorted(path.relative_to(ROOT).as_posix() for path in sources),
    }
    write_json(bundle / "bundle-manifest.json", manifest)
    return bundle


def safe_extract_zip(archive_path: Path, destination: Path) -> list[str]:
    """拒绝绝对路径和目录穿越后解压结果。"""
    import zipfile

    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"结果压缩包包含非法路径: {info.filename}")
            target = (destination / member).resolve()
            if target != destination.resolve() and destination.resolve() not in target.parents:
                raise ValueError(f"结果路径越界: {info.filename}")
            archive.extract(info, destination)
            if not info.is_dir():
                extracted.append(member.as_posix())
    return extracted
