"""TrendWear Planner — P2: integrated sales and operations planning.

Run locally:

    uvicorn trendwear.main:app --port 8002 --reload

The planning modules arrive in Tasks 16 to 21. This shell serves the interface
and a health endpoint so the two applications can be deployed and demonstrated
independently from the start — they share no data, no models and no runtime.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from trendwear.config import APP_NAME

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SHARED_DIR = Path(__file__).resolve().parents[4] / "packages" / "web"

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "app": APP_NAME, "loaded": False}


app = FastAPI(
    title=f"{APP_NAME} API",
    version="0.1.0",
    summary="Integrated S&OP for TrendWear Apparel (P2)",
)
app.include_router(router)

if SHARED_DIR.exists():
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
