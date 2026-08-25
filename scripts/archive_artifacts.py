"""为小问产物生成可复现归档清单，不移动或删除源文件。"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from automm.common import hash_path, relative, resolve_project_path, utc_now, write_json
from automm.tasks import list_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-dir", required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--code-path")
    parser.add_argument("--config-path")
    parser.add_argument("--input-path")
    parser.add_argument("--assumption-version", required=True)
    parser.add_argument("--formulation-version", required=True)
    parser.add_argument("--output-name", default="archive_manifest.json")
    args = parser.parse_args()
    question_dir = resolve_project_path(args.question_dir, must_exist=True)
    if not question_dir.is_dir():
        raise SystemExit("question-dir 必须是项目内目录")
    task_map = {task["task_id"]: task for task in list_tasks()}
    unknown = [task_id for task_id in args.task_id if task_id not in task_map]
    if unknown:
        raise SystemExit(f"未知 task ID：{', '.join(unknown)}")
    files = []
    for path in sorted(question_dir.rglob("*")):
        if path.is_file() and not path.name.startswith("archive_manifest"):
            files.append({"path": relative(path), "fingerprint_sha256": hash_path(path), "bytes": path.stat().st_size})
    manifest = {
        "updated_at": utc_now(),
        "question_directory": relative(question_dir),
        "assumption_version": args.assumption_version,
        "formulation_version": args.formulation_version,
        "task_ids": args.task_id,
        "task_statuses": {task_id: task_map[task_id].get("status") for task_id in args.task_id},
        "hashes": {
            "code": hash_path(args.code_path) if args.code_path else None,
            "config": hash_path(args.config_path) if args.config_path else None,
            "input": hash_path(args.input_path) if args.input_path else None,
        },
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "files": files,
    }
    output_name = Path(args.output_name)
    if output_name.name != args.output_name or output_name.suffix.lower() != ".json":
        raise SystemExit("output-name 必须是 question-dir 下的 JSON 文件名")
    output = question_dir / output_name
    if output.exists():
        raise SystemExit(f"归档清单已存在，拒绝覆盖：{relative(output)}")
    write_json(output, manifest)
    print(json.dumps({"manifest": relative(output), "file_count": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
