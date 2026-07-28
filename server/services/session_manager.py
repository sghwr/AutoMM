from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

from server.config import KaggleConfig
from server.db.database import Database
from server.services.log_writer import EventWriter


TERMINAL_STATUSES = {"DONE", "FAILED", "STOPPED", "INVALID"}
BUSY_STATUSES = {"STARTING", "PUSHING", "QUEUED", "RUNNING", "RETURNING", "STOP_REQUESTED"}


class WorkflowError(Exception):
    def __init__(self, error_code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.data = data or {}


class SessionManager:
    def __init__(self, db: Database, events: EventWriter, kaggle_config: KaggleConfig) -> None:
        self.db = db
        self.events = events
        self.kaggle_config = kaggle_config
        self.lock = Lock()

    def dashboard_state(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            sessions = [dict(row) for row in conn.execute("SELECT * FROM sessions ORDER BY session_id")]
            ready_queue = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT q.display_id, q.experiment_id, e.title, e.competition, e.kind,
                           q.status, q.created_at
                    FROM ready_queue q
                    JOIN experiments e ON e.id = q.experiment_id
                    WHERE q.status IN ('READY', 'SELECTED', 'INVALID')
                    ORDER BY q.position
                    """
                )
            ]
            selected_row = conn.execute(
                "SELECT display_id FROM ready_queue WHERE status = 'SELECTED' ORDER BY position LIMIT 1"
            ).fetchone()
            kaggle_running = conn.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE backend = 'kaggle' AND status IN ('STARTING','PUSHING','QUEUED','RUNNING','RETURNING')"
            ).fetchone()["count"]
            kaggle_gpu_running = conn.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE backend = 'kaggle' AND accelerator = 'gpu' AND status IN ('STARTING','PUSHING','QUEUED','RUNNING','RETURNING')"
            ).fetchone()["count"]
            local_busy = conn.execute(
                "SELECT status FROM sessions WHERE session_id = 0"
            ).fetchone()["status"] in BUSY_STATUSES
        return {
            "sessions": sessions,
            "ready_queue": ready_queue,
            "selected": selected_row["display_id"] if selected_row else None,
            "resources": {
                "kaggle_running": int(kaggle_running),
                "kaggle_limit": self.kaggle_config.session_limit,
                "kaggle_gpu_running": int(kaggle_gpu_running),
                "kaggle_gpu_limit": self.kaggle_config.gpu_limit,
                "local_busy": bool(local_busy),
            },
            "server_time": datetime.now().astimezone().isoformat(),
        }

    def select(self, display_id: str) -> dict[str, str]:
        now = datetime.now().astimezone().isoformat()
        with self.lock, self.db.connect() as conn:
            row = conn.execute("SELECT status FROM ready_queue WHERE display_id = ?", (display_id,)).fetchone()
            if row is None:
                raise WorkflowError("DISPLAY_ID_NOT_FOUND", f"{display_id} not found")
            if row["status"] != "READY":
                raise WorkflowError("EXPERIMENT_NOT_READY", f"{display_id} is not ready")
            conn.execute("UPDATE ready_queue SET status = 'READY', updated_at = ? WHERE status = 'SELECTED'", (now,))
            conn.execute(
                "UPDATE ready_queue SET status = 'SELECTED', updated_at = ? WHERE display_id = ?",
                (now, display_id),
            )
            conn.commit()
        self.events.write("EXPERIMENT_SELECTED", display_id=display_id)
        return {"selected": display_id}

    def accept_run(self, session_id: int, display_id: str | None, accelerator: str) -> dict[str, Any]:
        now = datetime.now().astimezone().isoformat()
        with self.lock, self.db.connect() as conn:
            session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if session is None:
                raise WorkflowError("SESSION_NOT_FOUND", f"session {session_id} not found")
            if session["status"] in BUSY_STATUSES:
                raise WorkflowError("SESSION_BUSY", f"session {session_id} is already running")
            selected = display_id or self._selected_display_id(conn)
            if selected is None:
                raise WorkflowError("NO_SELECTED_EXPERIMENT", "no experiment selected")
            queue_row = conn.execute(
                """
                SELECT q.experiment_id, q.status, e.entrypoint, e.kind
                FROM ready_queue q
                JOIN experiments e ON e.id = q.experiment_id
                WHERE q.display_id = ?
                """,
                (selected,),
            ).fetchone()
            if queue_row is None:
                raise WorkflowError("DISPLAY_ID_NOT_FOUND", f"{selected} not found")
            if queue_row["status"] not in {"READY", "SELECTED"}:
                raise WorkflowError("EXPERIMENT_NOT_READY", f"{selected} is not ready")
            if not queue_row["entrypoint"]:
                raise WorkflowError("ENTRYPOINT_NOT_FOUND", f"{selected} has no entrypoint")
            if session_id == 0 and accelerator == "gpu":
                accelerator = "none"
            if session_id > 0:
                self._check_kaggle_limits(conn, accelerator)

            backend = "local" if session_id == 0 else "kaggle"
            run_id = f"{backend}-s{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            conn.execute(
                """
                INSERT INTO runs
                    (run_id, experiment_id, session_id, backend, accelerator, status, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'STARTING', ?, ?)
                """,
                (run_id, queue_row["experiment_id"], session_id, backend, accelerator, now, now),
            )
            conn.execute(
                """
                UPDATE sessions
                SET status = 'STARTING', experiment_id = ?, display_id = ?, run_id = ?,
                    accelerator = ?, progress = 5, last_output_line = 'run accepted',
                    started_at = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (queue_row["experiment_id"], selected, run_id, accelerator, now, now, session_id),
            )
            conn.execute("UPDATE ready_queue SET status = 'RUNNING', updated_at = ? WHERE display_id = ?", (now, selected))
            conn.execute("UPDATE experiments SET status = 'RUNNING', updated_at = ? WHERE id = ?", (now, queue_row["experiment_id"]))
            conn.commit()

        self.events.write("RUN_ACCEPTED", session_id=session_id, display_id=selected, run_id=run_id)
        return {"session_id": session_id, "display_id": selected, "run_id": run_id, "status": "STARTING"}

    def update_session(self, session_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.now().astimezone().isoformat()
        names = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [session_id]
        with self.lock, self.db.connect() as conn:
            conn.execute(f"UPDATE sessions SET {names} WHERE session_id = ?", values)
            if "status" in fields:
                row = conn.execute("SELECT run_id FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
                if row and row["run_id"]:
                    conn.execute(
                        "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                        (fields["status"], fields["updated_at"], row["run_id"]),
                    )
            conn.commit()

    def finish_run(
        self,
        session_id: int,
        status: str,
        output_path: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        progress = 100 if status in {"DONE", "FAILED"} else None
        last_line = (
            f"[DONE] outputs saved to {output_path}"
            if status == "DONE" and output_path
            else error_message or status.lower()
        )
        with self.lock, self.db.connect() as conn:
            session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if session is None:
                return
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, progress = ?, output_path = ?, last_output_line = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status, progress, output_path, last_line, now, session_id),
            )
            if session["run_id"]:
                conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, output_path = ?, error_code = ?, error_message = ?,
                        exit_code = ?, finished_at = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (status, output_path, error_code, error_message, exit_code, now, now, session["run_id"]),
                )
            if session["experiment_id"]:
                conn.execute(
                    "UPDATE experiments SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, session["experiment_id"]),
                )
            conn.commit()
        self.events.write("RUN_FINISHED", session_id=session_id, status=status, output_path=output_path)

    def session_detail(self, session_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                raise WorkflowError("SESSION_NOT_FOUND", f"session {session_id} not found")
            return dict(row)

    def session_status(self, session_id: int) -> dict[str, Any]:
        session = self.session_detail(session_id)
        with self.db.connect() as conn:
            experiment = None
            run = None
            if session.get("experiment_id"):
                row = conn.execute("SELECT * FROM experiments WHERE id = ?", (session["experiment_id"],)).fetchone()
                experiment = dict(row) if row else None
            if session.get("run_id"):
                row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (session["run_id"],)).fetchone()
                run = dict(row) if row else None
        log_content = self.read_log(session_id, tail=None)["content"]
        return {"session": session, "experiment": experiment, "run": run, "script_output": log_content}

    def read_log(self, session_id: int, tail: int | None = 300) -> dict[str, Any]:
        session = self.session_detail(session_id)
        log_path = session.get("log_path")
        if not log_path:
            return {"session_id": session_id, "run_id": session.get("run_id"), "log_path": None, "content": "", "truncated": False}
        from pathlib import Path

        path = Path(log_path)
        if not path.exists():
            return {"session_id": session_id, "run_id": session.get("run_id"), "log_path": log_path, "content": "", "truncated": False}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        truncated = tail is not None and len(lines) > tail
        selected = lines[-tail:] if tail is not None else lines
        return {
            "session_id": session_id,
            "run_id": session.get("run_id"),
            "log_path": log_path,
            "content": "\n".join(selected),
            "truncated": truncated,
            "updated_at": datetime.now().astimezone().isoformat(),
        }

    def clear(self, session_id: int) -> dict[str, Any]:
        now = datetime.now().astimezone().isoformat()
        with self.lock, self.db.connect() as conn:
            row = conn.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                raise WorkflowError("SESSION_NOT_FOUND", f"session {session_id} not found")
            if row["status"] not in TERMINAL_STATUSES:
                raise WorkflowError("SESSION_NOT_CLEARABLE", f"session {session_id} is not clearable")
            conn.execute(
                """
                UPDATE sessions
                SET status = 'IDLE', experiment_id = NULL, display_id = NULL, run_id = NULL,
                    accelerator = 'none', gpu_label = NULL, progress = 0,
                    last_output_line = 'waiting for command', log_path = NULL, output_path = NULL,
                    kaggle_kernel_id = NULL, started_at = NULL, updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.commit()
        return {"session_id": session_id, "status": "IDLE"}

    def mark_stop_requested(self, session_id: int) -> dict[str, Any]:
        now = datetime.now().astimezone().isoformat()
        with self.lock, self.db.connect() as conn:
            row = conn.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                raise WorkflowError("SESSION_NOT_FOUND", f"session {session_id} not found")
            if row["status"] not in BUSY_STATUSES:
                raise WorkflowError("SESSION_NOT_RUNNING", f"session {session_id} is not running")
            conn.execute(
                "UPDATE sessions SET status = 'STOP_REQUESTED', last_output_line = 'stop requested', updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()
        return {"session_id": session_id, "status": "STOP_REQUESTED"}

    def _selected_display_id(self, conn: Any) -> str | None:
        row = conn.execute("SELECT display_id FROM ready_queue WHERE status = 'SELECTED' ORDER BY position LIMIT 1").fetchone()
        return row["display_id"] if row else None

    def _check_kaggle_limits(self, conn: Any, accelerator: str) -> None:
        running = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE backend = 'kaggle' AND status IN ('STARTING','PUSHING','QUEUED','RUNNING','RETURNING')"
        ).fetchone()["count"]
        if int(running) >= self.kaggle_config.session_limit:
            raise WorkflowError("KAGGLE_TOTAL_LIMIT_REACHED", "kaggle session limit reached")
        if accelerator == "gpu":
            gpu_running = conn.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE backend = 'kaggle' AND accelerator = 'gpu' AND status IN ('STARTING','PUSHING','QUEUED','RUNNING','RETURNING')"
            ).fetchone()["count"]
            if int(gpu_running) >= self.kaggle_config.gpu_limit:
                raise WorkflowError("KAGGLE_GPU_LIMIT_REACHED", "kaggle gpu limit reached")

