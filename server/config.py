from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {}
    return data


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    work_folder: Path
    scan_interval_seconds: int
    database_path: Path
    events_path: Path


@dataclass(frozen=True)
class KaggleConfig:
    username: str
    default_private: bool
    default_internet: bool
    gpu_limit: int
    session_limit: int


def load_server_config() -> ServerConfig:
    data = _read_yaml(ROOT / "configs" / "server.yaml")
    return ServerConfig(
        host=str(data.get("host", "0.0.0.0")),
        port=int(data.get("port", 8787)),
        work_folder=(ROOT / str(data.get("work_folder", "#Myworkfolder"))).resolve(),
        scan_interval_seconds=int(data.get("scan_interval_seconds", 5)),
        database_path=(ROOT / str(data.get("database_path", "state/workflow.sqlite"))).resolve(),
        events_path=(ROOT / str(data.get("events_path", "state/events.jsonl"))).resolve(),
    )


def load_kaggle_config() -> KaggleConfig:
    data = _read_yaml(ROOT / "configs" / "kaggle.yaml")
    return KaggleConfig(
        username=str(data.get("username", "your-kaggle-username")),
        default_private=bool(data.get("default_private", True)),
        default_internet=bool(data.get("default_internet", True)),
        gpu_limit=int(data.get("gpu_limit", 2)),
        session_limit=int(data.get("session_limit", 5)),
    )

