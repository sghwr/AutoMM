from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from server.db.database import Database
from server.services.log_writer import EventWriter


@dataclass(frozen=True)
class ScanResult:
    new_experiments: int
    invalid_experiments: int


class ExperimentScanner:
    def __init__(self, db: Database, events: EventWriter, work_folder: Path) -> None:
        self.db = db
        self.events = events
        self.work_folder = work_folder
        self._lock = Lock()

    def scan(self) -> ScanResult:
        with self._lock:
            self.work_folder.mkdir(parents=True, exist_ok=True)
            new_count = 0
            invalid_count = 0
            for ack_path in self.work_folder.glob("*/*/ACK.txt"):
                if self._is_registered(ack_path):
                    continue
                status = self._register(ack_path)
                if status == "INVALID":
                    invalid_count += 1
                else:
                    new_count += 1
            return ScanResult(new_count, invalid_count)

    def _is_registered(self, ack_path: Path) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM experiments WHERE ack_path = ?",
                (str(ack_path.resolve()),),
            ).fetchone()
        return row is not None

    def _register(self, ack_path: Path) -> str:
        workdir = ack_path.parent.resolve()
        config_path = workdir / "experiment.yaml"
        config = self._read_config(config_path)
        entrypoint = config.get("entrypoint")
        kind = config.get("kind")
        if not entrypoint or not kind:
            inferred = self._infer_entrypoint(workdir)
            entrypoint = entrypoint or inferred.get("entrypoint")
            kind = kind or inferred.get("kind", "unknown")

        status = "READY" if entrypoint and kind in {"python", "notebook"} else "INVALID"
        competition = str(config.get("competition") or workdir.parent.name)
        title = str(config.get("title") or workdir.name)
        now = datetime.now().astimezone().isoformat()
        experiment_id = self._make_experiment_id(workdir)

        with self.db.connect() as conn:
            display_id = self._next_display_id(conn)
            position = self._next_position(conn)
            conn.execute(
                """
                INSERT INTO experiments
                    (id, display_id, competition, title, workdir, entrypoint, kind, status,
                     ack_path, config_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    display_id,
                    competition,
                    title,
                    str(workdir),
                    entrypoint,
                    kind,
                    status,
                    str(ack_path.resolve()),
                    str(config_path.resolve()) if config_path.exists() else None,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO ready_queue
                    (display_id, experiment_id, status, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (display_id, experiment_id, status, position, now, now),
            )
            conn.commit()

        self.events.write(
            "EXPERIMENT_REGISTERED",
            display_id=display_id,
            experiment_id=experiment_id,
            status=status,
            workdir=str(workdir),
        )
        return status

    def _read_config(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}

    def _infer_entrypoint(self, workdir: Path) -> dict[str, str]:
        candidates = [
            path
            for path in list(workdir.glob("*.py")) + list(workdir.glob("*.ipynb"))
            if not path.name.startswith(".")
        ]
        if len(candidates) != 1:
            return {}
        path = candidates[0]
        return {
            "entrypoint": path.name,
            "kind": "notebook" if path.suffix == ".ipynb" else "python",
        }

    def _make_experiment_id(self, workdir: Path) -> str:
        return hashlib.sha1(str(workdir).encode("utf-8")).hexdigest()[:16]

    def _next_display_id(self, conn: Any) -> str:
        row = conn.execute("SELECT COUNT(*) AS count FROM ready_queue").fetchone()
        return f"exp{int(row['count']) + 1:03d}"

    def _next_position(self, conn: Any) -> int:
        row = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 AS position FROM ready_queue").fetchone()
        return int(row["position"])
