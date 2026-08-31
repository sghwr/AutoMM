from __future__ import annotations

from pathlib import Path

import pytest

from automm.problems import create_assumption_version, load_problem, problem_dir, question_manifest
from automm.state import apply_control, load_state, save_state
from automm.workflow import ensure_question_summary, question_summary_path, transition

pytestmark = pytest.mark.unit


def _accepted_version(problem_id: str) -> None:
    create_assumption_version(problem_id, "prob01")
    path, manifest = question_manifest(problem_id, "prob01")
    manifest["accepted_assumption_version"] = 1
    manifest["accepted_formulation_version"] = 1
    manifest["conclusion"] = {"conclusion_id": "c-prob01-v1", "version": 1, "content_hash": "abc"}
    manifest["sanity"] = {"level_1_4": "PASS"}
    manifest["optional_stages"] = {
        "robustness": {"decision": "completed", "reason": "fixture"},
        "ablation": {"decision": "completed", "reason": "fixture"},
    }
    manifest["artifacts"] = {
        "problem_understanding": True,
        "literature": True,
        "assumptions": True,
        "formulation": True,
        "implementation": True,
        "computation": True,
        "visualization": True,
        "sanity_check": True,
    }
    from automm.common import write_yaml

    write_yaml(path, manifest)


def test_ensure_question_summary_generates_substantive_file(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    _accepted_version(problem_id)
    path = ensure_question_summary(problem_id, "prob01")
    assert path == question_summary_path(problem_id, "prob01")
    text = path.read_text(encoding="utf-8")
    assert "c-prob01-v1" in text
    assert "待填写" not in text


def test_completed_transition_requires_built_summary(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    problem = load_problem(problem_id)
    problem["cross_question_review"] = "passed"
    from automm.common import write_json

    write_json(problem_dir(problem_id) / "problem_state.json", problem)
    state = load_state()
    state["current_stage"] = "cross_question_review"
    state["current_question"] = None
    save_state(state, event="test_setup")
    with pytest.raises(RuntimeError, match="最终摘要未生成"):
        transition(target_stage="completed", problem_id=problem_id, reason="test")


def test_resume_clears_human_blocked_recovery(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    state = load_state()
    state["recovery_status"] = "human_blocked"
    state["failure_class"] = "external_human_required"
    state["blocking"] = ["manual block"]
    state["recovery"] = {"mode": "convergence", "same_fingerprint_streak": 9}
    save_state(state, event="test_setup")
    applied = apply_control("RESUME", source="test")
    assert applied["recovery_status"] == "normal"
    assert applied["failure_class"] is None
    assert applied["blocking"] == []
    assert applied["recovery"]["mode"] == "normal"
    assert applied["recovery"]["same_fingerprint_streak"] == 0
