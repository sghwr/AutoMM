"""AutoMM 文献池命令入口。"""

from __future__ import annotations

import argparse
import json

from automm.research import (
    add_candidate,
    check_key_assumptions,
    decide_reference,
    finish_round,
    load_pool,
    start_round,
    verify_reference,
)


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 文献池管理器")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "check-key-assumptions"):
        item = sub.add_parser(name)
        item.add_argument("--problem-id", required=True)
        item.add_argument("--question-id", required=True)
    start = sub.add_parser("start-round")
    start.add_argument("--problem-id", required=True)
    start.add_argument("--question-id", required=True)
    start.add_argument("--query", required=True)
    add = sub.add_parser("add")
    add.add_argument("--problem-id", required=True)
    add.add_argument("--question-id", required=True)
    add.add_argument("--json", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--problem-id", required=True)
    verify.add_argument("--question-id", required=True)
    verify.add_argument("--reference-id", required=True)
    decide = sub.add_parser("decide")
    decide.add_argument("--problem-id", required=True)
    decide.add_argument("--question-id", required=True)
    decide.add_argument("--reference-id", required=True)
    decide.add_argument("--status", choices=("used", "rejected", "pending"), required=True)
    decide.add_argument("--reason", default="")
    finish = sub.add_parser("finish-round")
    finish.add_argument("--problem-id", required=True)
    finish.add_argument("--question-id", required=True)
    finish.add_argument(
        "--dry-reason",
        choices=("item_limit_reached", "time_limit_reached", "all_candidates_decided", "no_new_assumption_family"),
    )
    args = parser.parse_args()
    if args.action == "status":
        emit(load_pool(args.problem_id, args.question_id))
    elif args.action == "check-key-assumptions":
        emit(check_key_assumptions(args.problem_id, args.question_id))
    elif args.action == "start-round":
        emit(start_round(args.problem_id, args.question_id, args.query))
    elif args.action == "add":
        emit(add_candidate(args.problem_id, args.question_id, json.loads(args.json)))
    elif args.action == "verify":
        emit(verify_reference(args.problem_id, args.question_id, args.reference_id))
    elif args.action == "decide":
        emit(decide_reference(args.problem_id, args.question_id, args.reference_id, args.status, args.reason))
    elif args.action == "finish-round":
        emit(finish_round(args.problem_id, args.question_id, args.dry_reason))


if __name__ == "__main__":
    main()
