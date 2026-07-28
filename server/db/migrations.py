from __future__ import annotations

from server.db.database import Database


def migrate(db: Database) -> None:
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                display_id TEXT UNIQUE NOT NULL,
                competition TEXT NOT NULL,
                title TEXT NOT NULL,
                workdir TEXT NOT NULL UNIQUE,
                entrypoint TEXT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                ack_path TEXT NOT NULL UNIQUE,
                config_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ready_queue (
                display_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY,
                backend TEXT NOT NULL,
                status TEXT NOT NULL,
                experiment_id TEXT,
                display_id TEXT,
                run_id TEXT,
                accelerator TEXT NOT NULL DEFAULT 'none',
                gpu_label TEXT,
                progress INTEGER,
                last_output_line TEXT,
                log_path TEXT,
                output_path TEXT,
                kaggle_kernel_id TEXT,
                started_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                session_id INTEGER NOT NULL,
                backend TEXT NOT NULL,
                accelerator TEXT NOT NULL,
                status TEXT NOT NULL,
                process_id INTEGER,
                kaggle_kernel_id TEXT,
                kaggle_kernel_slug TEXT,
                log_path TEXT,
                output_path TEXT,
                exit_code INTEGER,
                error_code TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id)
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()


def ensure_default_sessions(db: Database) -> None:
    from datetime import datetime

    now = datetime.now().astimezone().isoformat()
    with db.connect() as conn:
        for session_id in range(6):
            backend = "local" if session_id == 0 else "kaggle"
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions
                    (session_id, backend, status, accelerator, progress, last_output_line, updated_at)
                VALUES (?, ?, 'IDLE', 'none', 0, 'waiting for command', ?)
                """,
                (session_id, backend, now),
            )
        conn.commit()

