from automm.failure_policy import note_recovery


def test_same_fingerprint_switches_to_convergence_before_degraded_review() -> None:
    state = {"recovery": {}}
    note_recovery(state, failure_class="code_runtime", error="same", progress={"productive": False})
    note_recovery(state, failure_class="code_runtime", error="same", progress={"productive": False})
    assert state["recovery"]["mode"] == "convergence"
    assert state["recovery_status"] == "retrying"


def test_ten_productive_rounds_enter_degraded_review() -> None:
    state = {"recovery": {}}
    for index in range(10):
        note_recovery(state, failure_class="code_runtime", error=f"error-{index}", progress={"productive": True, "code_hash": str(index)})
    assert state["recovery"]["productive_rounds"] == 10
    assert state["recovery_status"] == "degraded_review"
