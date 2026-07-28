from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ClientConfig(BaseModel):
    base_url: str
    refresh_interval_seconds: int = 2
    log_refresh_interval_seconds: int = 1
    request_timeout_seconds: int = 5


class ApiResult(BaseModel):
    ok: bool
    data: Any = None
    message: str = ""
    error_code: str | None = None

