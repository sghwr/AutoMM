from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from automm.agent_runtime import _validate_response_context, apply_agent_commands
from automm.failure_policy import HarnessInvariantError
from automm.llm import ProviderError, get_provider
from automm.llm.dsh import _parse_json_text
from automm.common import read_json
from automm.problems import question_manifest

pytestmark = pytest.mark.unit


def response(action_id: str = "act-test") -> dict:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "status": "success",
        "problem_id": "synthetic",
        "question_id": "prob01",
        "assumption_version": None,
        "formulation_version": None,
        "artifacts_created": [],
        "artifacts_updated": [],
        "findings": [],
        "warnings": [],
        "blocking_reasons": [],
        "recommended_next_stage": None,
        "commands": [],
    }


def test_response_context_mismatch_is_harness_invariant() -> None:
    payload = response()
    payload["question_id"] = "prob02"
    with pytest.raises(HarnessInvariantError, match="question_id"):
        _validate_response_context(payload, {"problem_id": "synthetic", "question_id": "prob01"})


def test_failed_response_cannot_change_state() -> None:
    payload = response()
    payload["status"] = "failed"
    payload["commands"] = [{"name": "record_artifact", "arguments": {"name": "literature", "completed": True}}]
    with pytest.raises(HarnessInvariantError, match="不得携带"):
        _validate_response_context(payload, {"problem_id": "synthetic", "question_id": "prob01"})


def test_command_batch_rejects_unknown_artifact_without_partial_write(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    payload = response()
    payload["problem_id"] = problem_id
    payload["commands"] = [
        {"name": "record_artifact", "arguments": {"name": "problem_understanding", "completed": True}},
        {"name": "record_artifact", "arguments": {"name": "not-a-logical-key", "completed": True}},
    ]
    with pytest.raises(HarnessInvariantError):
        apply_agent_commands(payload, {"problem_id": problem_id, "question_id": "prob01", "stage": "problem_understanding"})
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["artifacts"]["problem_understanding"] is False


def test_dsh_headless_command_is_argv_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    provider = get_provider({"provider": "dsh_headless", "executable": "dsh", "profile": "headless", "tools_mode": "native"})
    invocation = provider.prepare("hello task", Path("response.json"))
    assert invocation.command == ["dsh", "--profile", "headless", "hello task"]
    assert invocation.stdin is None
    assert invocation.env is not None and invocation.env["DSH_TOOLS_MODE"] == "native"


def test_codex_command_keeps_approval_and_sandbox_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider({"provider": "codex_exec", "executable": "codex", "output_schema": "config/agent_response.schema.json", "sandbox": "workspace-write", "automatic_approval": True, "skip_git_repo_check": True})
    invocation = provider.prepare("p", Path("response.json"))
    assert "--approve-for-me" in invocation.command
    assert "--sandbox" not in invocation.command
    assert invocation.stdin == "p"


def test_dsh_json_text_extraction() -> None:
    assert _parse_json_text("`json\n{\"a\": 1}\n`") == {"a": 1}
    assert _parse_json_text("prefix {\"a\": 1} suffix") == {"a": 1}
    with pytest.raises(ProviderError):
        _parse_json_text("no json here")


def test_command_batch_rolls_back_state_on_mid_batch_failure(initialized_problem: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    problem_id, _ = initialized_problem
    payload = response()
    payload["problem_id"] = problem_id
    payload["commands"] = [
        {"name": "record_artifact", "arguments": {"name": "problem_understanding", "completed": True}},
        {"name": "record_sanity", "arguments": {"level": "level_1_4", "status": "PASS", "reason": "fixture", "failure_type": None, "return_stage": None}},
    ]

    def fail_once(**_: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr("automm.agent_runtime.record_sanity", fail_once)
    with pytest.raises(HarnessInvariantError, match="已回滚"):
        apply_agent_commands(payload, {"problem_id": problem_id, "question_id": "prob01", "stage": "problem_understanding"})
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["artifacts"]["problem_understanding"] is False


def test_schema_enum_nodes_declare_type(project_root: Path) -> None:
    schema = read_json(project_root / "config" / "agent_response.schema.json")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "const" in node or "enum" in node:
                assert "type" in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    jsonschema.validate(response(), schema)
    walk(schema)
