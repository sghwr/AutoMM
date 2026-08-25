"""执行一个已登记的本地计算任务。"""

from __future__ import annotations

import argparse
import os
import subprocess
import traceback
from pathlib import Path

from automm.common import FileLock, ROOT, read_json, resolve_project_path, utc_now, write_json
from automm.tasks import TASK_ROOT

import psutil


def update_status(task_dir: Path, patch: dict) -> dict:
    path = task_dir / "status.json"
    status = read_json(path)
    status.update(patch)
    status["updated_at"] = utc_now()
    write_json(path, status)
    attempt_path = task_dir / f"attempt-{int(status.get('attempt', 1)):03d}-status.json"
    write_json(attempt_path, status)
    return status


def feasible_incumbent(output_dir: Path) -> bool:
    """读取求解器留下的可行解标记，不把退出码成功伪装成可行解。"""
    for name in ("feasible.json", "solver_status.json", "result.json"):
        path = output_dir / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and (payload.get("feasible_incumbent") or payload.get("incumbent_found")):
            return True
    return False


def terminate_tree(process: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    """跨平台终止任务子进程及其全部后代。"""
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
    except psutil.Error:
        descendants = []
        parent = None
    targets = [*descendants, *([parent] if parent is not None else [])]
    for target in reversed(targets):
        try:
            target.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=grace_seconds)
    for target in alive:
        try:
            target.kill()
        except psutil.Error:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=grace_seconds)


def run(task_id: str) -> int:
    task_dir = TASK_ROOT / task_id
    spec = read_json(task_dir / "task.json")
    if spec.get("task_id") != task_id:
        raise ValueError("task.json 的 task_id 与目录不一致")
    output_dir = resolve_project_path(spec["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(output_dir / ".automm-output.lock", stale_after_seconds=24 * 3600)
    if not lock.acquire(task_id):
        update_status(
            task_dir,
            {
                "status": "failed",
                "failure_type": "output_conflict",
                "failure_class": "harness_invariant",
                "message": "输出目录已被其他任务锁定",
                "finished_at": utc_now(),
            },
        )
        return 3

    attempt = int(spec.get("attempt", 1))
    stdout_path = task_dir / f"attempt-{attempt:03d}-stdout.log"
    stderr_path = task_dir / f"attempt-{attempt:03d}-stderr.log"
    try:
        update_status(
            task_dir,
            {
                "status": "running",
                "pid": os.getpid(),
                "worker_create_time": psutil.Process(os.getpid()).create_time(),
                "worker_started_at": utc_now(),
            },
        )
        write_json(task_dir / "worker_started.json", {"task_id": task_id, "pid": os.getpid(), "at": utc_now()})
        timeout = int(spec.get("timeout_seconds") or 0) or None
        environment = os.environ.copy()
        environment["AUTOMM_TASK_ID"] = task_id
        environment["AUTOMM_OUTPUT_DIR"] = str(output_dir)
        if spec.get("seed") is not None:
            environment["AUTOMM_SEED"] = str(spec["seed"])
            environment["PYTHONHASHSEED"] = str(spec["seed"])
        with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as stderr:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                [str(part) for part in spec["command"]],
                cwd=resolve_project_path(spec["working_directory"], must_exist=True),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                env=environment,
                start_new_session=os.name != "nt",
                creationflags=flags,
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate_tree(process)
                raise
        final = "succeeded" if returncode == 0 else "failed"
        update_status(
            task_dir,
            {
                "status": final,
                "returncode": returncode,
                "failure_type": None if final == "succeeded" else "process_exit",
                "failure_class": None if final == "succeeded" else "code_runtime",
                "finished_at": utc_now(),
                "stdout": str(stdout_path.relative_to(ROOT).as_posix()),
                "stderr": str(stderr_path.relative_to(ROOT).as_posix()),
                "feasible_incumbent": feasible_incumbent(output_dir),
            },
        )
        return returncode
    except subprocess.TimeoutExpired:
        update_status(
            task_dir,
            {
                "status": "timed_out",
                "failure_type": "timeout",
                "failure_class": "infrastructure_transient",
                "message": "任务超过 timeout_seconds",
                "finished_at": utc_now(),
                "stdout": str(stdout_path.relative_to(ROOT).as_posix()),
                "stderr": str(stderr_path.relative_to(ROOT).as_posix()),
                "feasible_incumbent": feasible_incumbent(output_dir),
            },
        )
        return 124
    except Exception as exc:  # worker 必须把异常转换为持久化终态
        (task_dir / "worker_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        update_status(
            task_dir,
            {
                "status": "failed",
                "failure_type": "worker_error",
                "failure_class": "infrastructure_transient",
                "message": str(exc),
                "finished_at": utc_now(),
                "stdout": str(stdout_path.relative_to(ROOT).as_posix()),
                "stderr": str(stderr_path.relative_to(ROOT).as_posix()),
            },
        )
        return 1
    finally:
        lock.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 本地任务 worker")
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.task_id))


if __name__ == "__main__":
    main()
