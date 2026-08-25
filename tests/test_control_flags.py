from __future__ import annotations

from automm.state import apply_control, load_state


def test_pause_resume_stop_flags(initialized_problem: tuple[str, object]) -> None:
    apply_control("PAUSE", source="test")
    assert load_state()["control"] == "paused"
    apply_control("RESUME", source="test")
    assert load_state()["control"] == "running"
    apply_control("STOP", source="test")
    assert load_state()["control"] == "stopped"
