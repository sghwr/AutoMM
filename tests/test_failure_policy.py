from automm.failure_policy import (
    AgentTimeoutError,
    HarnessInvariantError,
    classify_exception,
    error_fingerprint,
    note_recovery,
)


def test_timeout_is_transport_not_human_block() -> None:
    assert classify_exception(AgentTimeoutError("timeout")) == "agent_transport"


def test_invariant_is_strict() -> None:
    assert classify_exception(HarnessInvariantError("bad state")) == "harness_invariant"


def test_same_fingerprint_enters_convergence_mode() -> None:
    state = {"recovery": {}}
    note_recovery(state, failure_class="code_runtime", error="same", progress={"productive": False})
    note_recovery(state, failure_class="code_runtime", error="same", progress={"productive": False})
    assert state["recovery"]["same_fingerprint_streak"] == 2
    assert state["recovery"]["mode"] == "convergence"
    assert state["recovery_status"] == "retrying"


def test_productive_rounds_do_not_use_blind_retry_count() -> None:
    state = {"recovery": {}}
    for index in range(10):
        note_recovery(
            state,
            failure_class="code_runtime",
            error=f"error-{index}",
            progress={"productive": True, "code_hash": str(index)},
        )
    assert state["recovery"]["productive_rounds"] == 10
    assert state["recovery_status"] == "degraded_review"


def test_fingerprint_is_stable() -> None:
    assert error_fingerprint(failure_class="code_runtime", error="a  b") == error_fingerprint(failure_class="code_runtime", error="a b")
