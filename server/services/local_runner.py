from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from server.db.database import Database
from server.services.log_writer import append_log
from server.services.session_manager import SessionManager


PROGRESS_RE = re.compile(r"WORKFLOW_PROGRESS=(\d{1,3})")


class LocalRunner:
    def __init__(self, db: Database, sessions: SessionManager) -> None:
        self.db = db
        self.sessions = sessions

    def run(self, session_id: int, run_id: str) -> None:
        experiment = self._load_experiment(run_id)
        workdir = Path(experiment["workdir"])
        entrypoint = workdir / experiment["entrypoint"]
        log_path = workdir / "logs" / f"{run_id}.log"
        output_dir = workdir / "outputs" / "local" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        self.sessions.update_session(
            session_id,
            status="RUNNING",
            progress=10,
            log_path=str(log_path),
            output_path=str(output_dir),
            last_output_line=f"running {entrypoint.name}",
        )
        command = self._command_for(entrypoint, output_dir)
        env = os.environ.copy()
        env.update(
            {
                "WORKFLOW_RUN_ID": run_id,
                "WORKFLOW_OUTPUT_DIR": str(output_dir),
                "WORKFLOW_LOG_PATH": str(log_path),
            }
        )
        append_log(log_path, f"[STARTING] {' '.join(command)}")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self._save_process_id(run_id, process.pid)
            assert process.stdout is not None
            for line in process.stdout:
                append_log(log_path, line.rstrip("\n"))
                last_line = line.rstrip("\n")
                progress = self._parse_progress(last_line)
                fields = {"last_output_line": last_line}
                if progress is not None:
                    fields["progress"] = progress
                self.sessions.update_session(session_id, **fields)
            exit_code = process.wait()
            if exit_code == 0:
                self.sessions.finish_run(session_id, "DONE", output_path=str(output_dir), exit_code=exit_code)
            else:
                self.sessions.finish_run(
                    session_id,
                    "FAILED",
                    output_path=str(output_dir),
                    error_code="LOCAL_PROCESS_FAILED",
                    error_message=f"local process exited with {exit_code}",
                    exit_code=exit_code,
                )
        except FileNotFoundError as exc:
            self.sessions.finish_run(
                session_id,
                "FAILED",
                output_path=str(output_dir),
                error_code="LOCAL_COMMAND_NOT_FOUND",
                error_message=str(exc),
            )
        except Exception as exc:
            self.sessions.finish_run(
                session_id,
                "FAILED",
                output_path=str(output_dir),
                error_code="LOCAL_RUNNER_ERROR",
                error_message=str(exc),
            )

    def _load_experiment(self, run_id: str) -> dict[str, str]:
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

    def _command_for(self, entrypoint: Path, output_dir: Path) -> list[str]:
        if entrypoint.suffix == ".py":
            return [sys.executable, str(entrypoint.name)]
        if entrypoint.suffix == ".ipynb":
            return [
                sys.executable,
                "-m",
                "jupyter",
                "nbconvert",
                "--execute",
                "--to",
                "notebook",
                "--output",
                str(output_dir / f"executed-{datetime.now().strftime('%Y%m%d-%H%M%S')}.ipynb"),
                str(entrypoint.name),
            ]
        raise RuntimeError(f"unsupported entrypoint: {entrypoint}")

    def _parse_progress(self, line: str) -> int | None:
        match = PROGRESS_RE.search(line)
        if not match:
            return None
        return max(0, min(100, int(match.group(1))))

    def _save_process_id(self, run_id: str, process_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE runs SET process_id = ? WHERE run_id = ?", (process_id, run_id))
            conn.commit()
