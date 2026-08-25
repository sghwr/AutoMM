from __future__ import annotations

import pytest

from automm.failure_policy import AgentTimeoutError
from automm.runner import run_once
from automm.state import load_state

pytestmark = pytest.mark.integration


def test_agent_timeout_is_retrying_and_not_blocking(initialized_problem: tuple[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_: object, **__: object) -> None:
        raise AgentTimeoutError("injected timeout")

    monkeypatch.setattr("automm.runner.invoke_agent", timeout)
    result = run_once()
    state = load_state()
    assert result["status"] == "retrying"
    assert state["recovery_status"] == "retrying"
    assert state["blocking"] == []
