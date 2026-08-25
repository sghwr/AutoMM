from __future__ import annotations

import pytest

from automm.failure_policy import HarnessInvariantError, classify_exception
from automm.workflow import transition


def test_illegal_stage_transition_is_strict(initialized_problem: tuple[str, object]) -> None:
    problem_id, _ = initialized_problem
    with pytest.raises(RuntimeError):
        transition(target_stage="computation", problem_id=problem_id, question_id="prob01", reason="injected")


def test_invariant_never_becomes_model_warning() -> None:
    assert classify_exception(HarnessInvariantError("state mismatch")) == "harness_invariant"
