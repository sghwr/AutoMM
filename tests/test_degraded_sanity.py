from __future__ import annotations

import json
from pathlib import Path

from run_sanity_check import build_report


def test_feasible_incumbent_is_warning_not_failure(project_root: Path) -> None:
    output = project_root / "result"
    output.mkdir(exist_ok=True)
    (output / "result.json").write_text(json.dumps({"value": 1.0}), encoding="utf-8")
    report = build_report(output, None)
    assert report["automated_status"] == "PASS_WITH_WARNING"
    assert not report["failures"]


def test_nan_is_hard_failure(project_root: Path) -> None:
    output = project_root / "result"
    output.mkdir(exist_ok=True)
    (output / "result.json").write_text(json.dumps({"value": float("nan")}, allow_nan=True), encoding="utf-8")
    report = build_report(output, None)
    assert report["automated_status"] == "NEEDS_REVISION"
    assert report["failures"]
