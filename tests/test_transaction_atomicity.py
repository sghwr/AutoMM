from test_agent_runtime import test_command_batch_rolls_back_state_on_mid_batch_failure


def test_atomicity_regression_is_registered() -> None:
    assert callable(test_command_batch_rolls_back_state_on_mid_batch_failure)
