from __future__ import annotations

from fastapi import APIRouter, Request

from server.schemas import ApiResponse

router = APIRouter()


@router.get("/dashboard/state", response_model=ApiResponse)
def dashboard_state(request: Request) -> ApiResponse:
    return ApiResponse(ok=True, data=request.app.state.sessions.dashboard_state())

