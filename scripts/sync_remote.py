"""SSH/Kaggle 适配器的只读探测和任务生命周期入口。"""

from __future__ import annotations

import argparse
import json

from automm.remote.service import get_adapter, reconcile_remote, submit_remote


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("ssh", "kaggle"), required=True)
    parser.add_argument("--task-id")
    parser.add_argument("action", choices=("probe", "submit", "status", "pull"))
    args = parser.parse_args()
    if args.action == "probe":
        print(json.dumps(get_adapter(args.backend).probe(), ensure_ascii=False, indent=2))
        return
    if not args.task_id:
        raise SystemExit("submit/status/pull 必须提供 --task-id")
    if args.action == "submit":
        result = submit_remote(args.task_id)
    elif args.action == "status":
        result = reconcile_remote(args.task_id)
    else:
        result = reconcile_remote(args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
