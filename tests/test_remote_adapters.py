from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from automm.remote.base import AdapterError
from automm.remote.bundle import prepare_bundle, safe_extract_zip
from automm.remote.github import GitHubRelayAdapter, redact_secrets
from automm.remote.kaggle import KaggleAdapter
from automm.remote.ssh import SSHAdapter
from automm.remote.service import reconcile_remote, submit_remote
from automm.tasks import make_task_spec, submit_task

pytestmark = pytest.mark.unit


def test_bundle_rewrites_absolute_python_command(initialized_problem, project_root: Path) -> None:
    problem_id, _ = initialized_problem
    from test_tasks import _spec

    spec = _spec(problem_id, project_root)
    bundle = prepare_bundle(spec)
    payload = json.loads((bundle / "remote-task.json").read_text(encoding="utf-8"))
    assert payload["command"][0] == "python3"
    assert not Path(payload["command"][1]).is_absolute()
    assert (bundle / "runner.py").exists()


def test_safe_extract_rejects_zip_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="非法路径"):
        safe_extract_zip(archive, tmp_path / "out")


def test_github_redacts_nested_credentials() -> None:
    value = {"ssh": {"password": "secret"}, "list": [{"auth_token": "token"}], "safe": "ok"}
    assert redact_secrets(value) == {"ssh": {"password": ""}, "list": [{"auth_token": ""}], "safe": "ok"}


def test_kaggle_status_parser(monkeypatch, project_root: Path) -> None:
    adapter = KaggleAdapter({"enabled": True, "username": "u", "auth_token": "t"})

    class Result:
        stdout = "Status: COMPLETE"
        stderr = ""

    monkeypatch.setattr("automm.remote.kaggle.run_command", lambda *args, **kwargs: Result())
    assert adapter.status({"task_id": "x", "attempt": 1}, {"remote_job_id": "u/x"})["status"] == "succeeded"

    class EnumResult:
        stdout = 'u/x has status "KernelWorkerStatus.COMPLETE"'
        stderr = ""

    monkeypatch.setattr("automm.remote.kaggle.run_command", lambda *args, **kwargs: EnumResult())
    assert adapter.status({"task_id": "x", "attempt": 1}, {"remote_job_id": "u/x"})["status"] == "succeeded"


def test_kaggle_metadata_title_matches_slug(monkeypatch, project_root: Path) -> None:
    adapter = KaggleAdapter({"enabled": True, "username": "u", "auth_token": "t"})
    monkeypatch.setattr("automm.remote.kaggle.prepare_bundle", lambda spec: project_root / "data")
    stage = adapter._stage({"task_id": "smoke", "attempt": 2})
    metadata = json.loads((stage / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"].split("/", 1)[1] == metadata["title"]


def test_github_relay_rejects_disabled() -> None:
    with pytest.raises(AdapterError, match="未启用"):
        GitHubRelayAdapter({"enabled": False})


def test_ssh_windows_remote_dir_and_control_command() -> None:
    adapter = SSHAdapter(
        {
            "enabled": True,
            "platform": "windows",
            "remote_root": "D:/example-workdir",
        }
    )
    spec = {"task_id": "task-1", "attempt": 2}
    remote_dir = adapter._remote_dir(spec)
    assert remote_dir == "D:/example-workdir/tasks/task-1/attempt-002"
    command = adapter._windows_control_command(remote_dir, "check.ps1", "-Pid", "123")
    assert command == (
        "powershell -NoProfile -ExecutionPolicy Bypass -File "
        "D:/example-workdir/tasks/task-1/attempt-002/check.ps1 -Pid 123"
    )


def test_remote_service_preserves_state_and_pulls(monkeypatch, initialized_problem, project_root: Path) -> None:
    problem_id, _ = initialized_problem
    from test_tasks import _accepted_version

    code, config, input_path = _accepted_version(problem_id, project_root)
    output = project_root / "problems" / problem_id / "prob01" / "versions" / "assumption_v001" / "results" / "remote"
    spec = make_task_spec(
        problem_id=problem_id,
        question_id="prob01",
        stage="computation",
        command=[sys.executable, str(code)],
        code_path=str(code),
        config_path=str(config),
        input_path=str(input_path),
        assumption_version="assumption_v001",
        formulation_version="formulation_v001",
        output_directory=str(output),
        backend="ssh",
    )
    submit_task(spec)

    class Fake:
        def submit(self, value):
            assert value["task_id"] == spec["task_id"]
            return {"status": "running", "remote_job_id": "job-1"}

        def status(self, value, state):
            return {"status": "succeeded"}

        def pull(self, value, state):
            output.mkdir(parents=True, exist_ok=True)
            (output / "result.txt").write_text("42", encoding="utf-8")
            return {"result_files": ["result.txt"]}

    monkeypatch.setattr("automm.remote.service.get_adapter", lambda backend: Fake())
    assert submit_remote(spec["task_id"])["status"] == "running"
    final = reconcile_remote(spec["task_id"])
    assert final is not None and final["status"] == "succeeded"
    assert final["artifacts_pulled"] is True
    assert (output / "result.txt").read_text(encoding="utf-8") == "42"


def test_github_relay_local_bare_repository_roundtrip(project_root: Path, tmp_path: Path) -> None:
    remote = tmp_path / "relay.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    (project_root / "data" / "relay.txt").write_text("relay", encoding="utf-8")
    secret_config = project_root / "config" / "relay-secret.yaml"
    secret_config.write_text("password: do-not-push\nvisible: yes\n", encoding="utf-8")
    adapter = GitHubRelayAdapter(
        {
            "enabled": True,
            "repository": str(remote),
            "branch": "main",
            "push_paths": ["data", "config/relay-secret.yaml"],
            "pull_paths": ["data", "config/relay-secret.yaml"],
        }
    )
    adapter.worktree = tmp_path / "worktree"
    pushed = adapter.push()
    assert pushed["status"] == "pushed"
    staged = adapter.worktree / "config" / "relay-secret.yaml"
    assert "do-not-push" not in staged.read_text(encoding="utf-8")
    pulled = adapter.pull()
    assert pulled["status"] == "pulled"
    assert "password: ''" in secret_config.read_text(encoding="utf-8")
