from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from client.api.models import ApiResult, ClientConfig


ROOT = Path(__file__).resolve().parents[2]


def load_client_config() -> ClientConfig:
    path = ROOT / "configs" / "client.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return ClientConfig(**(data or {}))


class ServerClient:
    def __init__(self, config: ClientConfig) -> None:
        self.config = config
        self.http = httpx.Client(base_url=config.base_url, timeout=config.request_timeout_seconds)

    def close(self) -> None:
        self.http.close()

    def health(self) -> ApiResult:
        return self._get("/health")

    def dashboard_state(self) -> ApiResult:
        return self._get("/dashboard/state")

    def scan(self) -> ApiResult:
        return self._post("/experiments/scan", {})

    def select(self, display_id: str) -> ApiResult:
        return self._post("/queue/select", {"display_id": display_id})

    def run(self, session_id: int, display_id: str | None, accelerator: str) -> ApiResult:
        return self._post(f"/sessions/{session_id}/run", {"display_id": display_id, "accelerator": accelerator})

    def status(self, session_id: int) -> ApiResult:
        return self._get(f"/sessions/{session_id}/status")

    def log(self, session_id: int, tail: int | None = 300) -> ApiResult:
        path = f"/sessions/{session_id}/log"
        if tail is not None:
            path += f"?tail={tail}"
        return self._get(path)

    def session(self, session_id: int) -> ApiResult:
        return self._get(f"/sessions/{session_id}")

    def stop(self, session_id: int) -> ApiResult:
        return self._post(f"/sessions/{session_id}/stop", {"confirm": True})

    def clear(self, session_id: int) -> ApiResult:
        return self._post(f"/sessions/{session_id}/clear", {"confirm": True})

    def _get(self, path: str) -> ApiResult:
        try:
            response = self.http.get(path)
            return self._parse_response(response)
        except httpx.HTTPError as exc:
            return ApiResult(ok=False, error_code="CLIENT_REQUEST_FAILED", message=str(exc), data={})

    def _post(self, path: str, payload: dict[str, Any]) -> ApiResult:
        try:
            response = self.http.post(path, json=payload)
            return self._parse_response(response)
        except httpx.HTTPError as exc:
            return ApiResult(ok=False, error_code="CLIENT_REQUEST_FAILED", message=str(exc), data={})

    def _parse_response(self, response: httpx.Response) -> ApiResult:
        try:
            payload = response.json()
        except ValueError:
            return ApiResult(ok=False, error_code="INVALID_SERVER_RESPONSE", message=response.text, data={})
        return ApiResult(**payload)

