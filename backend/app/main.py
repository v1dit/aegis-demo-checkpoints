from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import eval as eval_api
from backend.app.api import replay as replay_api
from backend.app.api import stream as stream_api
from backend.app.api import train as train_api
from backend.app.core.paths import ensure_artifact_dirs

app = FastAPI(title="PantherHacks Track A API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(train_api.router)
app.include_router(eval_api.router)
app.include_router(replay_api.router)
app.include_router(stream_api.router)


@app.on_event("startup")
def _startup() -> None:
    ensure_artifact_dirs()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
