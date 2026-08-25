"""轻量本地任务监控：并发、重复任务、PID 与输出冲突。"""

from __future__ import annotations

import argparse
import json

from automm.tasks import effective_workers, list_tasks, reconcile_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-reconcile", action="store_true")
    args = parser.parse_args()
    changes = [] if args.no_reconcile else reconcile_tasks()
    tasks = list_tasks()
    payload = {"effective_workers": effective_workers(), "reconciled": changes, "tasks": tasks}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"本地有效并发槽位：{payload['effective_workers']}")
    if not tasks:
        print("没有任务")
    for task in tasks:
        print(
            f"{task.get('task_id', '?')}: {task.get('status', '?')} "
            f"backend={task.get('backend', '?')} pid={task.get('pid')}"
        )


if __name__ == "__main__":
    main()
