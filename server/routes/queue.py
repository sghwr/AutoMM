from __future__ import annotations

from fastapi import APIRouter, Request

from server.schemas import ApiResponse, SelectRequest

router = APIRouter()


@router.post("/queue/select", response_model=ApiResponse)
def select_experiment(payload: SelectRequest, request: Request) -> ApiResponse:
    data = request.app.state.sessions.select(payload.display_id)
    return ApiResponse(ok=True, data=data, message=f"selected {payload.display_id}")

