"""TrendWear Planner — P2: integrated sales and operations planning.

Run locally:

    uvicorn trendwear.main:app --port 8002 --reload

The planning context loads at startup from the cache written by
``python -m trendwear.pipeline``. Nothing is trained while the server is up.

This application shares no data, no models and no runtime with SupplyGuard. A
test in the repository fails the build if either one imports the other.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pyshared.logging import get_logger
from pyshared.telemetry import install as install_telemetry

from trendwear.api.routes import router
from trendwear.api.state import state
from trendwear.config import APP_NAME

log = get_logger(__name__)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SHARED_DIR = Path(__file__).resolve().parents[4] / "packages" / "web"

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("loading the planning context")
    state.load()
    log.info("warming the headline figures")
    state.warm()
    log.info("%s ready", APP_NAME)
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version="0.1.0",
    summary="Integrated S&OP for TrendWear Apparel (P2)",
    lifespan=lifespan,
)
@app.middleware("http")
async def revalidate_static(request, call_next):
    """Ask browsers to revalidate the front-end files rather than trust a copy."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/shared/", "/js/", "/css/", "/pages/")) or path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


install_telemetry(app)
app.include_router(router)

if SHARED_DIR.exists():
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
