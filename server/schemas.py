from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    ok: bool
    data: Any = Field(default_factory=dict)
    message: str = "ok"
    error_code: str | None = None


class RunRequest(BaseModel):
    display_id: str | None = None
    accelerator: Literal["none", "gpu"] = "none"


class SelectRequest(BaseModel):
    display_id: str


class ConfirmRequest(BaseModel):
    confirm: bool = False

