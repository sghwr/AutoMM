from __future__ import annotations

from fastapi import APIRouter, Request

from server.schemas import ApiResponse

router = APIRouter()


@router.post("/experiments/scan", response_model=ApiResponse)
def scan_experiments(request: Request) -> ApiResponse:
    result = request.app.state.scanner.scan()
    return ApiResponse(ok=True, data=result.__dict__, message="scan completed")

