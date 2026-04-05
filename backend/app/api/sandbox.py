from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.sandbox.jobs import (
    SandboxLiveUnavailableError,
    SandboxRateLimitError,
    SandboxValidationError,
    get_sandbox_catalog,
    get_sandbox_status,
    request_sandbox_cancel,
    start_sandbox_run,
)
from backend.app.schemas.contracts import (
    SandboxCancelResponse,
    SandboxCatalogResponse,
    SandboxRunCreateRequest,
    SandboxRunCreateResponse,
    SandboxRunStatusResponse,
)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.get("/catalog", response_model=SandboxCatalogResponse)
def sandbox_catalog() -> SandboxCatalogResponse:
    payload = get_sandbox_catalog()
    return SandboxCatalogResponse.model_validate(payload)


@router.post("/runs", response_model=SandboxRunCreateResponse)
def create_sandbox_run(
    request: Request, payload: SandboxRunCreateRequest
) -> SandboxRunCreateResponse:
    try:
        client_key = request.headers.get("x-forwarded-for")
        if not client_key and request.client:
            client_key = request.client.host
        run_id = start_sandbox_run(episode_spec=payload.episode_spec, client_key=client_key)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SandboxLiveUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SandboxRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    return SandboxRunCreateResponse(
        run_id=run_id,
        status="queued",
        stream_url=f"/stream/live/{run_id}",
    )


@router.get("/runs/{run_id}", response_model=SandboxRunStatusResponse)
def sandbox_run_status(run_id: str) -> SandboxRunStatusResponse:
    try:
        status = get_sandbox_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}") from exc
    return SandboxRunStatusResponse.model_validate(status)


@router.post("/runs/{run_id}/cancel", response_model=SandboxCancelResponse)
def cancel_sandbox_run(run_id: str) -> SandboxCancelResponse:
    try:
        status = request_sandbox_cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}") from exc
    return SandboxCancelResponse(run_id=run_id, status=status)
