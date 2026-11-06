"""FastAPI application for offline-trained anomaly model inference."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from service.model_runtime import ModelRuntime, load_runtime
from service.schemas import AnomalyScoreResponse, FeatureVector


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.model_runtime = load_runtime()
    yield
    app.state.model_runtime = None


app = FastAPI(
    title="Lathe Health Anomaly Inference",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(
    _request: Request, _error: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "INVALID_FEATURES",
                "message": "Provide exactly the approved finite numeric features.",
            },
        },
    )


@app.get("/health")
async def health() -> dict[str, object]:
    return {"success": True, "status": "running"}


@app.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    runtime = getattr(request.app.state, "model_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "status": "not_ready",
                "model_loaded": False,
            },
        )
    return {"success": True, "status": "ready", "model_loaded": True}


@app.post(
    "/api/v1/anomaly/score",
    response_model=AnomalyScoreResponse,
)
async def score_anomaly(
    payload: FeatureVector, request: Request
) -> dict[str, object]:
    runtime: ModelRuntime | None = getattr(request.app.state, "model_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "error": {
                    "code": "MODEL_NOT_READY",
                    "message": "The anomaly inference service is not ready.",
                },
            },
        )
    return runtime.score(payload.as_feature_dict())
