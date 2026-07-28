from __future__ import annotations

import time
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from server.app import app
from server.config import ROOT


def assert_ok(response):
    payload = response.json()
    assert payload["ok"], payload
    return payload["data"]


def main() -> None:
    experiment_name = f"smoke_exp_{int(time.time())}"
    workdir = ROOT / "#Myworkfolder" / "smoke_competition" / experiment_name
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "train.py").write_text(
        """
import os
from pathlib import Path

out = Path(os.environ["WORKFLOW_OUTPUT_DIR"])
out.mkdir(parents=True, exist_ok=True)
print("WORKFLOW_PROGRESS=30")
(out / "metrics.json").write_text('{"score": 1.0}', encoding="utf-8")
print("WORKFLOW_PROGRESS=100")
""".strip(),
        encoding="utf-8",
    )
    (workdir / "experiment.yaml").write_text(
        f"""
title: {experiment_name}
competition: smoke_competition
kind: python
entrypoint: train.py
outputs:
  expected:
    - metrics.json
""".strip(),
        encoding="utf-8",
    )
    (workdir / "ACK.txt").write_text("", encoding="utf-8")

    with TestClient(app) as client:
        assert_ok(client.get("/health"))
        assert_ok(client.post("/experiments/scan"))
        state = assert_ok(client.get("/dashboard/state"))
        item = next(row for row in state["ready_queue"] if row["title"] == experiment_name)
        display_id = item["display_id"]
        assert_ok(client.post("/queue/select", json={"display_id": display_id}))
        run = assert_ok(client.post("/sessions/0/run", json={"display_id": display_id, "accelerator": "none"}))
        assert run["status"] == "STARTING"
        for _ in range(60):
            session = assert_ok(client.get("/sessions/0")) 
            if session["status"] in {"DONE", "FAILED"}:
                break
            time.sleep(0.2)
        assert session["status"] == "DONE", session
        log = assert_ok(client.get("/sessions/0/log?tail=20"))
        assert "WORKFLOW_PROGRESS=100" in log["content"]

    print("smoke test passed")


if __name__ == "__main__":
    main()
