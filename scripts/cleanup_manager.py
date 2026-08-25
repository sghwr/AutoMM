"""AutoMM 可恢复清理命令入口；不提供永久删除。"""

from __future__ import annotations

import argparse
import json

from automm.cleanup import list_trash, move_to_trash


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 可恢复清理管理器")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    move = sub.add_parser("move")
    move.add_argument("--path", required=True)
    move.add_argument("--kind", choices=("cache", "temporary_conversion", "reproducible_intermediate"), required=True)
    move.add_argument("--reason", required=True)
    move.add_argument("--confirm", required=True)
    args = parser.parse_args()
    result = list_trash() if args.action == "list" else move_to_trash(args.path, args.kind, args.reason, args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
