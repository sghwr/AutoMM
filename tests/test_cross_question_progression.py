from __future__ import annotations

import pytest

from automm.problems import question_manifest
from automm.workflow import transition


def test_cross_question_review_rejects_incomplete_questions(initialized_problem: tuple[str, object]) -> None:
    problem_id, _ = initialized_problem
    with pytest.raises(RuntimeError):
        transition(target_stage="cross_question_review", problem_id=problem_id, reason="fixture")


def test_completion_metadata_is_required(initialized_problem: tuple[str, object]) -> None:
    problem_id, _ = initialized_problem
    _, manifest = question_manifest(problem_id, "prob01")
    assert not manifest.get("conclusion", {}).get("content_hash")
