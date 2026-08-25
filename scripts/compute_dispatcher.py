"""本地计算任务的提交、启动、查询与对账入口。"""

from __future__ import annotations

import argparse
import json

from automm.tasks import (
    cancel_queued,
    create_task_group,
    list_task_groups,
    list_tasks,
    make_task_spec,
    reconcile_tasks,
    start_queued,
    submit_task,
)


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AutoMM 计算调度器")
    sub = root.add_subparsers(dest="action", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--problem-id", required=True)
    submit.add_argument("--question-id", required=True)
    submit.add_argument("--stage", default="computation")
    submit.add_argument("--backend", choices=("local", "ssh", "kaggle"), default=None)
    submit.add_argument("--code-path", required=True)
    submit.add_argument("--config-path", required=True)
    submit.add_argument("--input-path", required=True)
    submit.add_argument("--assumption-version", required=True)
    submit.add_argument("--formulation-version", required=True)
    submit.add_argument("--output-directory", required=True)
    submit.add_argument("--working-directory", default=".")
    submit.add_argument("--timeout-seconds", type=int, default=0)
    submit.add_argument("--seed", type=int)
    submit.add_argument("--force", action="store_true")
    submit.add_argument("--force-reason")
    submit.add_argument("--group-id")
    submit.add_argument("command", nargs=argparse.REMAINDER)
    start = sub.add_parser("start")
    supervision = start.add_mutually_exclusive_group()
    supervision.add_argument("--supervised", action="store_true")
    supervision.add_argument("--detached", action="store_true")
    listing = sub.add_parser("list")
    listing.add_argument("--json", action="store_true")
    sub.add_parser("reconcile")
    sub.add_parser("cancel-queued")
    group = sub.add_parser("create-group")
    group.add_argument("--problem-id", required=True)
    group.add_argument("--question-id", required=True)
    group.add_argument("--stage", default="computation")
    group.add_argument("--expected-tasks", type=int, required=True)
    sub.add_parser("list-groups")
    return root


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    args = build_parser().parse_args()
    if args.action == "submit":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        spec = make_task_spec(
            problem_id=args.problem_id,
            question_id=args.question_id,
            stage=args.stage,
            command=command,
            code_path=args.code_path,
            config_path=args.config_path,
            input_path=args.input_path,
            assumption_version=args.assumption_version,
            formulation_version=args.formulation_version,
            output_directory=args.output_directory,
            working_directory=args.working_directory,
            timeout_seconds=args.timeout_seconds,
            seed=args.seed,
            group_id=args.group_id,
            backend=args.backend,
        )
        emit(submit_task(spec, force=args.force, force_reason=args.force_reason))
    elif args.action == "start":
        mode = True if args.supervised else False if args.detached else None
        emit(start_queued(supervised=mode))
    elif args.action == "list":
        tasks = list_tasks()
        if args.json:
            emit(tasks)
        elif not tasks:
            print("没有任务")
        else:
            for task in tasks:
                print(
                    f"{task.get('task_id', '?')} {task.get('status', '?')} "
                    f"{task.get('problem_id', '?')}/{task.get('question_id', '?')} "
                    f"pid={task.get('pid')}"
                )
    elif args.action == "reconcile":
        emit(reconcile_tasks())
    elif args.action == "cancel-queued":
        emit(cancel_queued())
    elif args.action == "create-group":
        emit(create_task_group(args.problem_id, args.question_id, args.stage, args.expected_tasks))
    elif args.action == "list-groups":
        emit(list_task_groups())


if __name__ == "__main__":
    main()
