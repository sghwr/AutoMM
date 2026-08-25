"""跨平台本地任务队列、任务指纹和状态对账。"""

from __future__ import annotations

import compileall
import importlib.util
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psutil

from .common import ROOT, RUNTIME_DIR, config_section, effective_config, hash_json, hash_path, read_json, read_yaml, relative, resolve_project_path, utc_now, write_json


TASK_ROOT = RUNTIME_DIR / "tasks"
GROUP_ROOT = RUNTIME_DIR / "task_groups"
TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "consumed", "archived"}
BACKENDS = {"local", "ssh", "kaggle"}


def preflight_python(code: Path) -> dict[str, Any]:
    python_files = [code] if code.is_file() and code.suffix.lower() == ".py" else list(code.rglob("*.py")) if code.is_dir() else []
    if not python_files:
        raise ValueError("初版本只支持 Python，code_path 必须包含 .py 文件")
    if code.is_file():
        compiled = compileall.compile_file(str(code), quiet=1, force=True)
    else:
        compiled = compileall.compile_dir(str(code), quiet=1, force=True)
    if not compiled:
        raise RuntimeError("代码未通过 compileall")
    ruff_executable = shutil.which("ruff")
    if not ruff_executable:
        # Ruff 是开发期质量工具，缺失不能把已经通过 compileall 的模型任务误判为不可行。
        return {"language": "python", "compileall": "passed", "ruff": "unavailable"}
    result = subprocess.run(
        [ruff_executable, "check", str(code)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"代码未通过 ruff：\n{result.stdout}{result.stderr}")
    return {"language": "python", "compileall": "passed", "ruff": "passed"}


def task_counts() -> dict[str, int]:
    return dict(Counter(item.get("status", "invalid") for item in list_tasks()))


def list_tasks() -> list[dict[str, Any]]:
    if not TASK_ROOT.exists():
        return []
    result = []
    for path in sorted(TASK_ROOT.glob("*/status.json")):
        try:
            status = read_json(path)
            status["task_dir"] = relative(path.parent)
            result.append(status)
        except (OSError, ValueError) as exc:
            result.append({"task_id": path.parent.name, "status": "invalid", "error": str(exc)})
    return result


def compute_task_id(spec: dict[str, Any]) -> str:
    identity = {
        "problem_id": spec["problem_id"],
        "question_id": spec["question_id"],
        "stage": spec["stage"],
        "code_hash": spec["code_hash"],
        "config_hash": spec["config_hash"],
        "input_hash": spec["input_hash"],
        "assumption_version": spec["assumption_version"],
        "formulation_version": spec["formulation_version"],
        "backend": spec["backend"],
    }
    return hash_json(identity)[:20]


def make_task_spec(
    *,
    problem_id: str,
    question_id: str,
    stage: str,
    command: list[str],
    code_path: str,
    config_path: str,
    input_path: str,
    assumption_version: str,
    formulation_version: str,
    output_directory: str,
    working_directory: str = ".",
    timeout_seconds: int = 0,
    seed: int | None = None,
    group_id: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    if not command:
        raise ValueError("任务命令不能为空")
    merged_config = effective_config(problem_id, question_id, config_path)
    compute_config = merged_config.get("compute", {})
    default_backend = str(compute_config.get("default_backend", "local")).lower()
    if default_backend not in BACKENDS:
        raise ValueError(f"配置 compute.default_backend 非法：{default_backend}；可选值为 local、ssh、kaggle")
    # 热修复：backend 唯一权威来源 = 配置 default_backend；显式 --backend 一律忽略（守住「必须 ssh」硬约束）
    backend = default_backend
    if "--output" in command:
        output_index = command.index("--output")
        if output_index + 1 >= len(command):
            raise ValueError("--output 必须提供 output_directory")
        if resolve_project_path(str(command[output_index + 1])) != resolve_project_path(output_directory):
            raise ValueError("--output 必须与 output_directory 一致")
    executable = Path(str(command[0])).name.lower()
    if executable not in {"python", "python3", "python.exe", Path(sys.executable).name.lower()}:
        raise ValueError("初版本只允许 Python 任务命令")
    code = resolve_project_path(code_path, must_exist=True)
    task_config = resolve_project_path(config_path, must_exist=True)
    task_input = resolve_project_path(input_path, must_exist=True)
    output = resolve_project_path(output_directory)
    workdir = resolve_project_path(working_directory, must_exist=True)
    from .problems import problem_dir, question_manifest

    _, manifest = question_manifest(problem_id, question_id)
    version_root = problem_dir(problem_id) / question_id / "versions" / assumption_version
    if not version_root.is_dir():
        raise ValueError(f"假设版本目录不存在：{assumption_version}")
    if output != version_root and version_root not in output.parents:
        raise ValueError("output_directory 必须位于指定小问的假设版本目录内")
    accepted_or_active = {
        f"assumption_v{int(manifest.get('active_assumption_version', 0)):03d}",
        f"assumption_v{int(manifest.get('accepted_assumption_version', 0)):03d}",
    }
    if assumption_version not in accepted_or_active:
        raise ValueError("任务假设版本既不是活动版本，也不是已接受版本")
    expected_formulation = f"formulation_v{int(manifest.get('accepted_formulation_version', 0)):03d}"
    if formulation_version != expected_formulation:
        raise ValueError(f"任务公式版本不是已接受版本：期望 {expected_formulation}")
    if not (version_root / "formulations" / formulation_version).is_dir():
        raise ValueError(f"公式版本目录不存在：{formulation_version}")
    preflight = preflight_python(code)
    spec = {
        "problem_id": problem_id,
        "question_id": question_id,
        "stage": stage,
        "command": command,
        "working_directory": relative(workdir),
        "output_directory": relative(output),
        "code_path": relative(code),
        "config_path": relative(task_config),
        "input_path": relative(task_input),
        "code_hash": hash_path(code),
        "config_hash": hash_json(merged_config),
        "source_config_hash": hash_path(task_config),
        "input_hash": hash_path(task_input),
        "assumption_version": assumption_version,
        "formulation_version": formulation_version,
        "timeout_seconds": timeout_seconds or int(compute_config.get("task_timeout_seconds", 0)),
        "seed": seed,
        "group_id": group_id,
        "backend": backend,
        "preflight": preflight,
        "created_at": utc_now(),
    }
    spec["task_id"] = compute_task_id(spec)
    return spec


def create_task_group(problem_id: str, question_id: str, stage: str, expected_tasks: int) -> dict[str, Any]:
    if expected_tasks < 1:
        raise ValueError("expected_tasks 至少为 1")
    payload = {"problem_id": problem_id, "question_id": question_id, "stage": stage, "expected_tasks": expected_tasks}
    group_id = f"grp-{hash_json({**payload, 'created_at': utc_now()})[:16]}"
    group = {"group_id": group_id, **payload, "task_ids": [], "status": "open", "created_at": utc_now()}
    write_json(GROUP_ROOT / group_id / "group.json", group)
    return group


def load_task_group(group_id: str) -> dict[str, Any]:
    path = GROUP_ROOT / group_id / "group.json"
    if not path.exists():
        raise FileNotFoundError(f"任务批次不存在：{group_id}")
    return read_json(path)


def list_task_groups(problem_id: str | None = None, question_id: str | None = None) -> list[dict[str, Any]]:
    result = []
    for path in sorted(GROUP_ROOT.glob("*/group.json")) if GROUP_ROOT.exists() else []:
        group = read_json(path)
        if problem_id and group.get("problem_id") != problem_id:
            continue
        if question_id and group.get("question_id") != question_id:
            continue
        statuses = [read_json(TASK_ROOT / task_id / "status.json", default={}).get("status", "missing") for task_id in group.get("task_ids", [])]
        group["task_statuses"] = statuses
        group["ready"] = len(statuses) == int(group["expected_tasks"]) and all(status in TERMINAL for status in statuses)
        result.append(group)
    return result


def _attempt_numbers(directory: Path) -> list[int]:
    numbers: set[int] = set()
    for path in directory.glob("attempt-*.json"):
        parts = path.stem.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            numbers.add(int(parts[1]))
    return sorted(numbers)


def submit_task(spec: dict[str, Any], *, force: bool = False, force_reason: str | None = None) -> dict[str, Any]:
    if spec.get("stage") == "implementation":
        raise ValueError("implementation 阶段不得创建正式计算 task；请先完成静态检查，再由 computation 阶段提交")
    task_id = spec["task_id"]
    group = None
    if spec.get("group_id"):
        group = load_task_group(spec["group_id"])
        if (group["problem_id"], group["question_id"], group["stage"]) != (spec["problem_id"], spec["question_id"], spec["stage"]):
            raise ValueError("任务与批次上下文不一致")
        if task_id not in group["task_ids"] and len(group["task_ids"]) >= int(group["expected_tasks"]):
            raise RuntimeError("任务批次已达到 expected_tasks")
    directory = TASK_ROOT / task_id
    old_status = read_json(directory / "status.json", default={})
    if old_status.get("status") in {"running", "queued"}:
        raise RuntimeError(f"运行中或排队任务禁止重复提交: {task_id} status={old_status['status']}")
    if old_status.get("status") == "succeeded" and not force:
        raise RuntimeError(f"重复任务已阻止: {task_id} status={old_status['status']}")
    if force and not str(force_reason or "").strip():
        raise ValueError("--force 必须同时提供 --force-reason")
    directory.mkdir(parents=True, exist_ok=True)
    attempt = (_attempt_numbers(directory)[-1] + 1) if _attempt_numbers(directory) else 1
    if force and (directory / "task.json").exists():
        old_spec = read_json(directory / "task.json")
        if old_spec.get("output_directory") == spec.get("output_directory"):
            raise ValueError("强制重跑必须使用新的 output_directory，避免覆盖旧结果")
        compute = config_section("compute", spec["problem_id"], spec["question_id"])
        failure_type = old_status.get("failure_type")
        retry_policy = compute.get("retry", {})
        retries = (
            int(compute.get("timeout_retry_attempts", 2))
            if failure_type in {"timeout", "interrupted"}
            else int(retry_policy.get("infrastructure_transient", compute.get("timeout_retry_attempts", 3)))
            if failure_type in {"infrastructure_transient"}
            else int(retry_policy.get("code_runtime", compute.get("code_repair_attempts", 1)))
            if failure_type in {"process_exit", "worker_error", "code_runtime"}
            else int(retry_policy.get("model_revision", compute.get("max_retries", 2)))
        )
        if attempt > retries + 1:
            raise RuntimeError(f"任务已达到重试上限：failure_type={failure_type} retries={retries}")
        spec["force_reason"] = force_reason
    spec = dict(spec)
    spec["attempt"] = attempt
    spec["force_reason"] = force_reason
    write_json(directory / f"attempt-{attempt:03d}-task.json", spec)
    write_json(directory / "task.json", spec)
    status = {
        "task_id": task_id,
        "attempt": attempt,
        "problem_id": spec["problem_id"],
        "question_id": spec["question_id"],
        "stage": spec["stage"],
        "backend": spec["backend"],
        "status": "queued",
        "pid": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "consumed": False,
        "force_reason": force_reason,
        "group_id": spec.get("group_id"),
        "failure_class": None,
        "worker_mode": "supervised",
    }
    write_json(directory / f"attempt-{attempt:03d}-status.json", status)
    write_json(directory / "status.json", status)
    if spec.get("group_id"):
        assert group is not None
        if task_id not in group["task_ids"]:
            group["task_ids"].append(task_id)
            group["status"] = "sealed" if len(group["task_ids"]) == int(group["expected_tasks"]) else "open"
            write_json(GROUP_ROOT / spec["group_id"] / "group.json", group)
    return status


def effective_workers(problem_id: str | None = None, question_id: str | None = None) -> int:
    config = config_section("compute", problem_id, question_id)
    configured = int(config.get("max_local_concurrent_tasks", 4))
    cpu_slots = max(1, (os.cpu_count() or 2) - 1)
    memory_per = max(0.25, float(config.get("memory_per_worker_gb", 2)))
    memory_slots = max(1, int(psutil.virtual_memory().available / (memory_per * 1024**3)))
    return max(1, min(configured, cpu_slots, memory_slots))


def _running_count() -> int:
    return sum(1 for item in list_tasks() if item.get("status") == "running" and worker_alive(item))


def start_queued(*, supervised: bool = False) -> list[dict[str, Any]]:
    queued = [item for item in list_tasks() if item.get("status") == "queued"]
    remote_queued = [item for item in queued if item.get("backend") in {"ssh", "kaggle"}]
    local_queued = [item for item in queued if item.get("backend") not in {"ssh", "kaggle"}]
    started = []
    if remote_queued:
        from .remote.service import submit_remote

        for status in remote_queued:
            started.append(submit_remote(status["task_id"]))
    if not local_queued:
        return started
    context = local_queued[0] if local_queued else {}
    slots = max(0, effective_workers(context.get("problem_id"), context.get("question_id")) - _running_count())
    if slots == 0:
        return started
    worker = ROOT / "scripts" / "task_worker.py"
    for status in local_queued[:slots]:
        task_id = status["task_id"]
        if supervised:
            current = read_json(TASK_ROOT / task_id / "status.json")
            current.update({"status": "running", "pid": os.getpid(), "started_at": utc_now(), "updated_at": utc_now()})
            write_json(TASK_ROOT / task_id / "status.json", current)
            write_json(TASK_ROOT / task_id / f"attempt-{int(current['attempt']):03d}-status.json", current)
            from task_worker import run as run_worker

            run_worker(task_id)
            started.append(read_json(TASK_ROOT / task_id / "status.json"))
            continue
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, str(worker), "--task-id", task_id],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=flags,
        )
        status_path = TASK_ROOT / task_id / "status.json"
        current = read_json(status_path)
        if current.get("status") == "queued":
            try:
                create_time = psutil.Process(process.pid).create_time()
            except psutil.Error:
                create_time = None
            current.update(
                {
                    "status": "running",
                    "pid": process.pid,
                    "worker_create_time": create_time,
                    "started_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            write_json(status_path, current)
            write_json(TASK_ROOT / task_id / f"attempt-{int(current['attempt']):03d}-status.json", current)
        started.append(current)
    return started


def pid_alive(pid: Any) -> bool:
    try:
        return bool(pid) and psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).is_running()
    except (ValueError, TypeError, psutil.Error):
        return False


def worker_alive(status: dict[str, Any]) -> bool:
    """校验 PID、进程创建时间和 worker 命令行，避免 PID 复用误判。"""
    try:
        pid = int(status["pid"])
        process = psutil.Process(pid)
        if not process.is_running():
            return False
        expected_time = status.get("worker_create_time")
        if expected_time is not None and abs(process.create_time() - float(expected_time)) > 1.0:
            return False
        command = " ".join(process.cmdline()).replace("\\", "/")
        expected = f"task_worker.py --task-id {status['task_id']}"
        return expected in command
    except (KeyError, ValueError, TypeError, psutil.Error):
        return False


def reconcile_tasks() -> list[dict[str, Any]]:
    changes = []
    for status in list_tasks():
        if status.get("status") != "running":
            continue
        if status.get("backend") in {"ssh", "kaggle"}:
            from .remote.service import reconcile_remote

            updated = reconcile_remote(status["task_id"])
            if updated and updated.get("status") != "running":
                changes.append(updated)
            continue
        if worker_alive(status):
            continue
        path = TASK_ROOT / status["task_id"] / "status.json"
        current = read_json(path)
        if current.get("status") == "running":
            current.update(
                {
                    "status": "failed",
                    "failure_type": "interrupted",
                    "failure_class": "infrastructure_transient",
                    "message": "worker PID 不存在且未写入终态",
                    "finished_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            write_json(path, current)
            write_json(
                TASK_ROOT / status["task_id"] / f"attempt-{int(current.get('attempt', 1)):03d}-status.json",
                current,
            )
            changes.append(current)
    return changes


def cancel_queued() -> list[str]:
    cancelled = []
    for status in list_tasks():
        if status.get("status") != "queued":
            continue
        status.update({"status": "cancelled", "finished_at": utc_now(), "updated_at": utc_now()})
        write_json(TASK_ROOT / status["task_id"] / "status.json", status)
        write_json(
            TASK_ROOT / status["task_id"] / f"attempt-{int(status.get('attempt', 1)):03d}-status.json",
            status,
        )
        cancelled.append(status["task_id"])
    return cancelled
