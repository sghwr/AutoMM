"""生成整题最终研究摘要。"""

from __future__ import annotations

import argparse
import json

from automm.state import load_state
from automm.summary import build_final_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem-id")
    args = parser.parse_args()
    problem_id = args.problem_id or load_state().get("active_problem")
    if not problem_id:
        raise SystemExit("没有活动题目")
    print(json.dumps(build_final_summary(problem_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
