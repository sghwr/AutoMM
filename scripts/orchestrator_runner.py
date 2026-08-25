"""AutoMM 单次 Orchestrator 唤醒入口。"""

from __future__ import annotations

import argparse
import json
import sys

from automm.runner import run_once


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoMM 单次 Orchestrator 唤醒")
    parser.parse_args()
    result = run_once()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] in {"completed", "pending_coalesced"} else 1


if __name__ == "__main__":
    # Windows 默认代码页可能无法编码中文；强制 CLI 输出 UTF-8，便于 Runner 和测试读取。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
