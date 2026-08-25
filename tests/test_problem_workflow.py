from __future__ import annotations

from pathlib import Path

import pytest
from automm.common import read_json, read_yaml, write_yaml
from automm.problems import (
    create_assumption_version,
    create_formulation_version,
    decide_assumption_version,
    decide_formulation_version,
    init_problem,
    problem_dir,
    question_manifest,
)
from automm.state import apply_control, load_state
from automm.workflow import next_action, record_conclusion, record_sanity, transition

pytestmark = pytest.mark.unit


def _add_verified_reference(problem_id: str, question_id: str) -> None:
    pool_path = problem_dir(problem_id) / question_id / "shared" / "literature_pool.yaml"
    pool = read_yaml(pool_path)
    pool["items"] = [{"id": "ref-1", "status": "used", "verified": True}]
    write_yaml(pool_path, pool)


def test_init_problem_creates_sequential_questions(project_root: Path) -> None:
    target = init_problem("demo", 3)
    state = load_state()
    problem = read_json(target / "problem_state.json")
    assert problem["questions"] == ["prob01", "prob02", "prob03"]
    assert state["active_problem"] == "demo"
    assert state["current_stage"] == "problem_understanding"
    assert next_action()["agent"] == "problem-decomposer"


def test_init_problem_rejects_duplicate(initialized_problem: tuple[str, Path]) -> None:
    with pytest.raises(RuntimeError, match="未关闭"):
        init_problem("another", 1)


def test_transition_enforces_assumption_gate(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    transition(target_stage="literature_review", problem_id=problem_id, question_id="prob01", reason="test")
    transition(target_stage="assumption_definition", problem_id=problem_id, question_id="prob01", reason="test")
    with pytest.raises(RuntimeError, match="已接受的假设"):
        transition(target_stage="mathematical_formulation", problem_id=problem_id, question_id="prob01", reason="test")


def test_assumption_and_formulation_versions_are_immutable_candidates(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    transition(target_stage="literature_review", problem_id=problem_id, question_id="prob01", reason="test")
    transition(target_stage="assumption_definition", problem_id=problem_id, question_id="prob01", reason="test")
    version = create_assumption_version(problem_id, "prob01")
    _add_verified_reference(problem_id, "prob01")
    decided = decide_assumption_version(problem_id, "prob01", "ACCEPT", "证据充分")
    assert decided["accepted_assumption_version"] == 1
    formulation = create_formulation_version(problem_id, "prob01")
    accepted = decide_formulation_version(problem_id, "prob01", "ACCEPT", "公式检查通过")
    assert accepted["status"] == "accepted"
    assert version.exists() and formulation.exists()
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["accepted_formulation_version"] == 1
    assert load_state()["current_stage"] == "implementation"


def test_control_commands_change_policy(initialized_problem: tuple[str, Path], project_root: Path) -> None:
    apply_control("PAUSE", source="test")
    assert next_action()["action"] == "poll_email"
    apply_control("RESUME", source="test")
    assert next_action()["action"] == "run_agent"
    assert (project_root / "runtime" / "flags" / "pending_wakeup.flag").exists()
    apply_control("STOP", source="test")
    assert next_action()["action"] == "poll_email"


def test_blocking_requires_resume_before_next_agent(initialized_problem: tuple[str, Path]) -> None:
    from automm.state import save_state

    state = load_state()
    state["blocking"] = ["human action required"]
    save_state(state, event="test_setup")
    assert next_action()["action"] == "blocked"
    apply_control("RESUME", source="test")
    assert load_state()["blocking"] == []
    assert next_action()["action"] == "run_agent"


def test_computation_can_return_to_formulation_after_boundary_failure(
    initialized_problem: tuple[str, Path],
) -> None:
    problem_id, _ = initialized_problem
    state = load_state()
    state["current_stage"] = "computation"
    from automm.state import save_state

    save_state(state, event="test_setup")
    path, manifest = question_manifest(problem_id, "prob01")
    manifest["stage"] = "computation"
    manifest["accepted_assumption_version"] = 1
    write_yaml(path, manifest)

    result = transition(
        target_stage="mathematical_formulation",
        problem_id=problem_id,
        question_id="prob01",
        reason="pricing support boundary is infeasible",
    )

    assert result["current_stage"] == "mathematical_formulation"


def test_conclusion_change_marks_all_downstream_questions_stale(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    first = record_conclusion(problem_id, "prob01", "c1", "value=10")
    second = record_conclusion(problem_id, "prob01", "c1", "value=11")
    assert first["stale_questions"] == []
    assert second["stale_questions"] == ["prob02", "prob03"]
    for question_id in ("prob02", "prob03"):
        _, manifest = question_manifest(problem_id, question_id)
        assert manifest["stale"]["value"] is True
        assert manifest["stage"] == "assumption_definition"


def test_sanity_revision_routes_to_implementation(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    state = load_state()
    state["current_stage"] = "sanity_check"
    from automm.state import save_state

    save_state(state, event="test_setup")
    _, manifest = question_manifest(problem_id, "prob01")
    manifest["stage"] = "sanity_check"
    manifest["accepted_formulation_version"] = 1
    path, _ = question_manifest(problem_id, "prob01")
    write_yaml(path, manifest)
    result = record_sanity(problem_id, "prob01", "level_1_4", "NEEDS_REVISION", "代码输出错误", "code_or_runtime")
    assert result["routed_to"] == "implementation"
    assert load_state()["current_stage"] == "implementation"


def test_next_action_selects_level_6_after_robustness(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    state = load_state()
    state["current_stage"] = "sanity_check"
    from automm.state import save_state

    save_state(state, event="test_setup")
    path, manifest = question_manifest(problem_id, "prob01")
    manifest["stage"] = "sanity_check"
    manifest["sanity"]["level_1_4"] = "PASS_WITH_WARNING"
    manifest["sanity"]["level_6"] = "NEEDS_REVISION"
    manifest["sanity_history"] = [
        {"level": "level_6", "status": "NEEDS_REVISION"},
        {"level": "level_1_4", "status": "PASS_WITH_WARNING"},
    ]
    manifest["optional_stages"]["robustness"] = {"decision": "completed", "reason": "fixture"}
    write_yaml(path, manifest)

    action = next_action()

    assert action["agent"] == "sanity-checker"
    assert action["level"] == "level_6"


def test_completed_robustness_does_not_rerun_visualization_or_robustness(
    initialized_problem: tuple[str, Path],
) -> None:
    problem_id, _ = initialized_problem
    state = load_state()
    state["current_stage"] = "visualization"
    from automm.state import save_state

    save_state(state, event="test_setup")
    path, manifest = question_manifest(problem_id, "prob01")
    manifest["stage"] = "visualization"
    manifest["artifacts"]["visualization"] = True
    manifest["optional_stages"]["robustness"] = {"decision": "completed", "reason": "fixture"}
    write_yaml(path, manifest)

    action = next_action()

    assert action["action"] == "advance_stage"
    assert action["stage"] == "sanity_check"
