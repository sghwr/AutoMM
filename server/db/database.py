from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def execute(self, sql: str, params: Iterable[object] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, tuple(params))
            conn.commit()

