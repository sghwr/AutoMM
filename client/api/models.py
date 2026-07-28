from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ClientConfig(BaseModel):
    base_url: str
    refresh_interval_seconds: float = 1
    log_refresh_interval_seconds: float = 1
    request_timeout_seconds: float = 5


class ApiResult(BaseModel):
    ok: bool
    data: Any = None
    message: str = ""
    error_code: str | None = None
