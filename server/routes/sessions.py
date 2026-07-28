from __future__ import annotations

import threading

from fastapi import APIRouter, Request

from server.schemas import ApiResponse, ConfirmRequest, RunRequest

router = APIRouter()


@router.post("/sessions/{session_id}/run", response_model=ApiResponse)
def run_session(session_id: int, payload: RunRequest, request: Request) -> ApiResponse:
    data = request.app.state.sessions.accept_run(session_id, payload.display_id, payload.accelerator)
    runner = request.app.state.local_runner if session_id == 0 else request.app.state.kaggle_runner
    thread = threading.Thread(target=runner.run, args=(session_id, data["run_id"]), daemon=True)
    thread.start()
    return ApiResponse(ok=True, data=data, message="accepted")


@router.get("/sessions/{session_id}/status", response_model=ApiResponse)
def session_status(session_id: int, request: Request) -> ApiResponse:
    return ApiResponse(ok=True, data=request.app.state.sessions.session_status(session_id))


@router.get("/sessions/{session_id}/log", response_model=ApiResponse)
def session_log(session_id: int, request: Request, tail: int | None = 300) -> ApiResponse:
    return ApiResponse(ok=True, data=request.app.state.sessions.read_log(session_id, tail=tail))


@router.get("/sessions/{session_id}", response_model=ApiResponse)
def session_detail(session_id: int, request: Request) -> ApiResponse:
    return ApiResponse(ok=True, data=request.app.state.sessions.session_detail(session_id))


@router.post("/sessions/{session_id}/stop", response_model=ApiResponse)
def stop_session(session_id: int, payload: ConfirmRequest, request: Request) -> ApiResponse:
    if not payload.confirm:
        return ApiResponse(ok=False, error_code="CONFIRM_REQUIRED", message="confirm is required")
    data = request.app.state.sessions.mark_stop_requested(session_id)
    return ApiResponse(ok=True, data=data, message="stop requested")


@router.post("/sessions/{session_id}/clear", response_model=ApiResponse)
def clear_session(session_id: int, payload: ConfirmRequest, request: Request) -> ApiResponse:
    if not payload.confirm:
        return ApiResponse(ok=False, error_code="CONFIRM_REQUIRED", message="confirm is required")
    data = request.app.state.sessions.clear(session_id)
    return ApiResponse(ok=True, data=data, message="session cleared")

