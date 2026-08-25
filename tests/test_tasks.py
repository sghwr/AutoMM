from __future__ import annotations

import sys
from pathlib import Path

import pytest
from automm.common import read_json, read_yaml, write_json, write_yaml
from automm.problems import create_assumption_version, create_formulation_version, problem_dir, question_manifest
from automm.tasks import compute_task_id, make_task_spec, start_queued, submit_task
from task_worker import run

pytestmark = pytest.mark.unit


def _accepted_version(problem_id: str, project_root: Path) -> tuple[Path, Path, Path]:
    from automm.state import load_state, save_state

    state = load_state()
    state["current_stage"] = "assumption_definition"
    save_state(state, event="test_setup")
    version_dir = create_assumption_version(problem_id, "prob01")
    formulation_dir = create_formulation_version(problem_id, "prob01")
    formulation = read_yaml(formulation_dir / "formulation.yaml")
    formulation["status"] = "accepted"
    write_yaml(formulation_dir / "formulation.yaml", formulation)
    manifest_path, manifest = question_manifest(problem_id, "prob01")
    manifest["accepted_formulation_version"] = 1
    write_yaml(manifest_path, manifest)
    code = version_dir / "code" / "compute.py"
    code.write_text(
        "import os\nfrom pathlib import Path\n\n"
        "Path(os.environ['AUTOMM_OUTPUT_DIR']).joinpath('result.txt').write_text('42', encoding='utf-8')\n",
        encoding="utf-8",
    )
    config = version_dir / "task_config.yaml"
    write_yaml(config, {"compute": {"max_local_concurrent_tasks": 1}})
    input_path = project_root / "data" / "input.txt"
    input_path.write_text("input", encoding="utf-8")
    return code, config, input_path


def _spec(problem_id: str, project_root: Path, output_name: str = "run-1") -> dict:
    code, config, input_path = _accepted_version(problem_id, project_root)
    output = problem_dir(problem_id) / "prob01" / "versions" / "assumption_v001" / "results" / output_name
    return make_task_spec(
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
        timeout_seconds=10,
        seed=7,
    )


def test_task_id_uses_declared_identity() -> None:
    base = {
        "problem_id": "p",
        "question_id": "prob01",
        "stage": "computation",
        "code_hash": "a",
        "config_hash": "b",
        "input_hash": "c",
        "assumption_version": "assumption_v001",
        "formulation_version": "formulation_v001",
        "backend": "local",
    }
    assert compute_task_id(base) == compute_task_id({**base, "ignored": 1})
    assert compute_task_id(base) != compute_task_id({**base, "input_hash": "different"})


def test_task_id_separates_compute_backend() -> None:
    base = {
        "problem_id": "p",
        "question_id": "prob01",
        "stage": "computation",
        "code_hash": "a",
        "config_hash": "b",
        "input_hash": "c",
        "assumption_version": "assumption_v001",
        "formulation_version": "formulation_v001",
        "backend": "local",
    }
    assert compute_task_id(base) != compute_task_id({**base, "backend": "ssh"})


def test_task_command_output_must_match_declared_directory(
    initialized_problem: tuple[str, Path], project_root: Path
) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    wrong_output = str(Path(spec["output_directory"]).parent / "wrong-output")

    with pytest.raises(ValueError, match="--output 必须与 output_directory 一致"):
        make_task_spec(
            problem_id=problem_id,
            question_id="prob01",
            stage="computation",
            command=[*spec["command"], "--output", wrong_output],
            code_path=spec["code_path"],
            config_path=spec["config_path"],
            input_path=spec["input_path"],
            assumption_version="assumption_v001",
            formulation_version="formulation_v001",
            output_directory=spec["output_directory"],
            timeout_seconds=10,
            seed=7,
        )


def test_submit_blocks_duplicate_queued_task(initialized_problem: tuple[str, Path], project_root: Path) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    assert submit_task(spec)["status"] == "queued"
    with pytest.raises(RuntimeError, match="重复提交"):
        submit_task(spec)


def test_worker_executes_task_and_writes_terminal_status(
    initialized_problem: tuple[str, Path], project_root: Path
) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    submit_task(spec)
    assert run(spec["task_id"]) == 0
    status = read_json(project_root / "runtime" / "tasks" / spec["task_id"] / "status.json")
    assert status["status"] == "succeeded"
    output = project_root / spec["output_directory"] / "result.txt"
    assert output.read_text(encoding="utf-8") == "42"


def test_supervised_start_waits_for_terminal_status(
    initialized_problem: tuple[str, Path], project_root: Path
) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    submit_task(spec)
    statuses = start_queued(supervised=True)
    assert statuses[0]["status"] == "succeeded"


def test_force_rerun_requires_reason_and_new_output(initialized_problem: tuple[str, Path], project_root: Path) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    submit_task(spec)
    run(spec["task_id"])
    with pytest.raises(ValueError, match="force-reason"):
        submit_task(spec, force=True)
    with pytest.raises(ValueError, match="新的 output_directory"):
        submit_task(spec, force=True, force_reason="reproduce")


def test_interrupted_task_allows_two_retries(initialized_problem: tuple[str, Path], project_root: Path) -> None:
    problem_id, _ = initialized_problem
    spec = _spec(problem_id, project_root)
    first = submit_task(spec)
    task_dir = project_root / "runtime" / "tasks" / spec["task_id"]
    failed = {**first, "status": "failed", "failure_type": "interrupted"}
    write_json(task_dir / "status.json", failed)

    for attempt, output_name in ((2, "run-2"), (3, "run-3")):
        retry = {**spec, "output_directory": str(Path(spec["output_directory"]).parent / output_name)}
        status = submit_task(retry, force=True, force_reason="worker interrupted")
        assert status["attempt"] == attempt
        write_json(task_dir / "status.json", {**status, "status": "failed", "failure_type": "interrupted"})

    exhausted = {**spec, "output_directory": str(Path(spec["output_directory"]).parent / "run-4")}
    with pytest.raises(RuntimeError, match="重试上限"):
        submit_task(exhausted, force=True, force_reason="worker interrupted")


def test_default_backend_from_config_routes_compute(initialized_problem: tuple[str, Path], project_root: Path) -> None:
    problem_id, _ = initialized_problem
    code, config, input_path = _accepted_version(problem_id, project_root)
    write_yaml(config, {"compute": {"max_local_concurrent_tasks": 1, "default_backend": "ssh"}})
    output = problem_dir(problem_id) / "prob01" / "versions" / "assumption_v001" / "results" / "run-remote"
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
        timeout_seconds=10,
        seed=7,
    )
    assert spec["backend"] == "ssh"
