from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from server.config import ROOT, KaggleConfig
from server.db.database import Database
from server.services.log_writer import append_log
from server.services.session_manager import SessionManager


class KaggleRunner:
    def __init__(self, db: Database, sessions: SessionManager, config: KaggleConfig) -> None:
        self.db = db
        self.sessions = sessions
        self.config = config

    def run(self, session_id: int, run_id: str) -> None:
        experiment = self._load_experiment(run_id)
        workdir = Path(experiment["workdir"])
        entrypoint = workdir / experiment["entrypoint"]
        log_path = workdir / "logs" / f"{run_id}.log"
        output_dir = workdir / "outputs" / "kaggle" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            run = self._load_run(run_id)
            exp_config = self._read_experiment_yaml(workdir)
            metadata = self._build_metadata(experiment, exp_config, entrypoint, run["accelerator"], run_id)
            kernel_id = metadata["id"]
            staging_dir = ROOT / "state" / "kaggle_staging" / run_id
            staging_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entrypoint, staging_dir / entrypoint.name)
            (staging_dir / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            self._update_run_kernel(run_id, kernel_id, metadata["id"].split("/", 1)[1])
            self.sessions.update_session(
                session_id,
                status="PUSHING",
                progress=15,
                log_path=str(log_path),
                output_path=str(output_dir),
                kaggle_kernel_id=kernel_id,
                last_output_line=f"pushing {kernel_id}",
            )
            self._run_command(["kaggle", "kernels", "push", "-p", str(staging_dir)], log_path)
            self.sessions.update_session(session_id, status="QUEUED", progress=25, last_output_line="kernel accepted")
            self._poll_status(session_id, kernel_id, log_path)
            self.sessions.update_session(session_id, status="RETURNING", progress=90, last_output_line="pulling outputs")
            self._run_command(["kaggle", "kernels", "output", kernel_id, "-p", str(output_dir)], log_path)
            missing = self._missing_expected_outputs(exp_config, output_dir)
            if missing:
                self.sessions.finish_run(
                    session_id,
                    "FAILED",
                    output_path=str(output_dir),
                    error_code="EXPECTED_OUTPUT_MISSING",
                    error_message=f"missing expected outputs: {', '.join(missing)}",
                )
                return
            self.sessions.finish_run(session_id, "DONE", output_path=str(output_dir), exit_code=0)
        except FileNotFoundError as exc:
            self.sessions.finish_run(
                session_id,
                "FAILED",
                output_path=str(output_dir),
                error_code="KAGGLE_CLI_NOT_AVAILABLE",
                error_message=str(exc),
            )
        except subprocess.CalledProcessError as exc:
            self.sessions.finish_run(
                session_id,
                "FAILED",
                output_path=str(output_dir),
                error_code="KAGGLE_COMMAND_FAILED",
                error_message=f"kaggle command failed with {exc.returncode}",
                exit_code=exc.returncode,
            )
        except Exception as exc:
            self.sessions.finish_run(
                session_id,
                "FAILED",
                output_path=str(output_dir),
                error_code="KAGGLE_RUNNER_ERROR",
                error_message=str(exc),
            )

    def _load_experiment(self, run_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT e.* FROM runs r
                JOIN experiments e ON e.id = r.experiment_id
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"run {run_id} not found")
        return dict(row)

    def _load_run(self, run_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"run {run_id} not found")
        return dict(row)

    def _read_experiment_yaml(self, workdir: Path) -> dict[str, Any]:
        path = workdir / "experiment.yaml"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}

    def _build_metadata(
        self,
        experiment: dict[str, Any],
        exp_config: dict[str, Any],
        entrypoint: Path,
        accelerator: str,
        run_id: str,
    ) -> dict[str, Any]:
        kaggle = exp_config.get("kaggle") if isinstance(exp_config.get("kaggle"), dict) else {}
        slug = str(kaggle.get("kernel_slug") or f"{experiment['display_id']}-{run_id}").lower().replace("_", "-")
        metadata: dict[str, Any] = {
            "id": f"{self.config.username}/{slug}",
            "title": str(exp_config.get("title") or experiment["title"]),
            "code_file": entrypoint.name,
            "language": "python",
            "kernel_type": "notebook" if entrypoint.suffix == ".ipynb" else "script",
            "is_private": bool(kaggle.get("is_private", self.config.default_private)),
            "enable_gpu": accelerator == "gpu",
            "enable_internet": bool(kaggle.get("internet", self.config.default_internet)),
        }
        dataset_sources: list[str] = []
        competition_sources: list[str] = []
        for source in kaggle.get("dataset_sources", []) or []:
            if not isinstance(source, dict):
                continue
            if source.get("type") == "competition":
                competition_sources.append(str(source.get("ref")))
            elif source.get("type") == "dataset":
                dataset_sources.append(str(source.get("ref")))
        if dataset_sources:
            metadata["dataset_sources"] = dataset_sources
        if competition_sources:
            metadata["competition_sources"] = competition_sources
        return metadata

    def _run_command(self, command: list[str], log_path: Path) -> None:
        append_log(log_path, f"$ {' '.join(command)}")
        process = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
        if process.stdout:
            append_log(log_path, process.stdout.rstrip())
        if process.stderr:
            append_log(log_path, process.stderr.rstrip())
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)

    def _poll_status(self, session_id: int, kernel_id: str, log_path: Path) -> None:
        for _ in range(720):
            process = subprocess.run(
                ["kaggle", "kernels", "status", kernel_id],
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = (process.stdout or process.stderr or "").strip()
            append_log(log_path, output or "status poll returned no output")
            lower = output.lower()
            self.sessions.update_session(session_id, status="RUNNING", progress=50, last_output_line=output[-240:] or "running")
            if "complete" in lower:
                return
            if "error" in lower or "failed" in lower:
                raise RuntimeError(output or "kaggle kernel failed")
            time.sleep(30)
        raise RuntimeError("kaggle status polling timed out")

    def _missing_expected_outputs(self, exp_config: dict[str, Any], output_dir: Path) -> list[str]:
        outputs = exp_config.get("outputs") if isinstance(exp_config.get("outputs"), dict) else {}
        expected = outputs.get("expected", []) or []
        return [str(name) for name in expected if not (output_dir / str(name)).exists()]

    def _update_run_kernel(self, run_id: str, kernel_id: str, kernel_slug: str) -> None:
        now = datetime.now().astimezone().isoformat()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE runs SET kaggle_kernel_id = ?, kaggle_kernel_slug = ?, updated_at = ? WHERE run_id = ?",
                (kernel_id, kernel_slug, now, run_id),
            )
            conn.commit()

