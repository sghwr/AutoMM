"""执行显式 GitHub 代码与结果中转。"""

from __future__ import annotations

import argparse
import json

from automm.common import ROOT, append_jsonl, read_yaml, relative, resolve_project_path, utc_now
from automm.remote.github import GitHubRelayAdapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("push", "pull"))
    parser.add_argument("--paths", nargs="*")
    args = parser.parse_args()
    relay = read_yaml(ROOT / "config" / "compute.yaml").get("github_relay", {})
    configured = relay.get("push_paths" if args.action == "push" else "pull_paths", [])
    selected = args.paths if args.paths is not None else configured
    if not selected:
        raise SystemExit("GitHub 中转路径为空")
    normalized = [relative(resolve_project_path(path)) for path in selected]
    adapter = GitHubRelayAdapter(relay)
    if args.action == "push":
        result = adapter.push(normalized, message="AutoMM relay update")
    else:
        result = adapter.pull(normalized)
    record = {"at": utc_now(), "action": args.action, "paths": normalized, **result}
    append_jsonl(ROOT / "runtime" / "github_relay_requests.jsonl", record)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
