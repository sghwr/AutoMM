from __future__ import annotations

import argparse
from pathlib import Path


TEMPLATE = """\
import os
from pathlib import Path

output_dir = Path(os.environ.get("WORKFLOW_OUTPUT_DIR", "outputs"))
output_dir.mkdir(parents=True, exist_ok=True)
print("WORKFLOW_PROGRESS=20")
print("hello from AutoMM experiment")
print("WORKFLOW_PROGRESS=100")
(output_dir / "metrics.json").write_text('{"ok": true}', encoding="utf-8")
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("competition")
    parser.add_argument("experiment")
    args = parser.parse_args()
    workdir = Path("#Myworkfolder") / args.competition / args.experiment
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "train.py").write_text(TEMPLATE, encoding="utf-8")
    (workdir / "experiment.yaml").write_text(
        f"""title: {args.experiment}
competition: {args.competition}
kind: python
entrypoint: train.py
outputs:
  expected:
    - metrics.json
""",
        encoding="utf-8",
    )
    (workdir / "ACK.txt").write_text("", encoding="utf-8")
    print(workdir)


if __name__ == "__main__":
    main()

