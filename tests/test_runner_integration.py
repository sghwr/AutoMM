from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from automm.problems import question_manifest
from automm.runner import recover_incomplete_transactions, run_once

pytestmark = pytest.mark.integration


def test_prompt_contains_degraded_quality_contract(project_root: Path) -> None:
    prompt = (project_root / "agents" / "sanity-checker.md").read_text(encoding="utf-8")
    assert "PASS_WITH_WARNING" in prompt
    assert "mip_gap" in prompt
    assert "NaN/Inf" in prompt


def test_implementation_prompt_forbids_long_computation(project_root: Path) -> None:
    prompt = (project_root / "agents" / "implementation-agent.md").read_text(encoding="utf-8")
    assert "完整数据集" in prompt
    assert "supervised worker" in prompt
    assert "commands" in prompt


def test_orchestrator_runner_help_does_not_execute_action(project_root: Path) -> None:
    action_root = project_root / "runtime" / "actions"
    before = set(action_root.glob("*"))
    script = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator_runner.py"
    result = subprocess.run([sys.executable, str(script), "--help"], cwd=project_root, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert set(action_root.glob("*")) == before


def test_transaction_recovery_marks_unfinished_action(tmp_path: Path) -> None:
    journal = tmp_path / "transactions.jsonl"
    journal.write_text('{"action_id":"act-1","phase":"started"}\n', encoding="utf-8")
    assert recover_incomplete_transactions(journal) == ["act-1"]


def test_problem_conclusion_metadata_is_written(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    from automm.workflow import record_conclusion

    record_conclusion(problem_id, "prob01", "c1", "synthetic conclusion")
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["conclusion"]["conclusion_id"] == "c1"
    assert manifest["conclusion"]["content_hash"]
