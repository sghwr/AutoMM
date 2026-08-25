"""跨平台前台 daemon；周期调用 one-shot Runner。"""

from __future__ import annotations

import argparse
import os
import time

import psutil
from automm.common import ROOT, FileLock, read_yaml, utc_now, write_text
from automm.runner import run_once

WAIT_ACTIONS = {
    "await_problem_initialization",
    "blocked",
    "idle",
    "poll_email",
    "wait_for_compute",
}


def should_continue_immediately(result: dict) -> bool:
    action = result.get("action", {})
    return result.get("status") == "completed" and action.get("action") not in WAIT_ACTIONS


def wait_for_wakeup(seconds: int, pending_path, *, check_interval: float = 1.0) -> bool:
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        if pending_path.exists():
            pending_path.unlink()
            return True
        time.sleep(min(check_interval, max(0, deadline - time.monotonic())))
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = read_yaml(ROOT / "config" / "orchestrator.yaml")
    daemon = config.get("daemon", {})
    pid_path = ROOT / daemon.get("pid_file", "runtime/daemon/daemon.pid")
    daemon_lock = FileLock(ROOT / daemon.get("lock_file", "runtime/daemon/daemon.lock"), 365 * 24 * 3600)
    stop_path = ROOT / daemon.get("stop_flag", "runtime/daemon/stop.flag")
    log_path = ROOT / daemon.get("log_file", "runtime/daemon/daemon.log")
    pending_path = ROOT / read_yaml(ROOT / "config" / "workflow.yaml").get("flags", {}).get(
        "pending_wakeup", "runtime/flags/pending_wakeup.flag"
    )
    if not daemon_lock.acquire(f"daemon-{os.getpid()}"):
        info = daemon_lock.info()
        try:
            owner_alive = psutil.Process(int(info.get("pid", 0))).is_running()
        except (ValueError, TypeError, psutil.Error):
            owner_alive = False
        if owner_alive:
            raise SystemExit(f"DAEMON_ALREADY_RUNNING: {info}")
        daemon_lock.release()
        if not daemon_lock.acquire(f"daemon-{os.getpid()}"):
            raise SystemExit("DAEMON_LOCK_RECOVERY_FAILED")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(pid_path, f"pid={os.getpid()}\nstarted_at={utc_now()}\n")
    try:
        while True:
            result = run_once()
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{utc_now()} {result}\n")
            if args.once or stop_path.exists():
                break
            if daemon.get("catch_up_pending_wakeup", True) and pending_path.exists():
                pending_path.unlink()
                continue
            if config.get("immediate_followup_when_runnable", True) and should_continue_immediately(result):
                continue
            if wait_for_wakeup(max(1, int(config.get("poll_interval_seconds", 600))), pending_path):
                continue
    finally:
        if pid_path.exists():
            pid_path.unlink()
        if stop_path.exists():
            stop_path.unlink()
        daemon_lock.release()


if __name__ == "__main__":
    main()
