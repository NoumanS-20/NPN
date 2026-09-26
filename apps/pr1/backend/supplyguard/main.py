"""SupplyGuard — PR1: procurement planning, supplier allocation and risk prediction.

Run locally:

    uvicorn supplyguard.main:app --port 8001 --reload

The planning context loads at startup from the cache written by
``python -m supplyguard.pipeline``. Nothing is trained while the server is up.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pyshared.logging import get_logger
from pyshared.telemetry import install as install_telemetry

from supplyguard.api.routes import router
from supplyguard.api.state import state
from supplyguard.config import APP_NAME

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
    summary="Supplier allocation and delivery-risk prediction (PR1)",
    lifespan=lifespan,
)

# The frontend is served from the same origin in production; CORS is here so a
# developer can run the static files on a different port while iterating.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5501", "http://127.0.0.1:5501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def revalidate_static(request, call_next):
    """Ask browsers to revalidate the front-end files rather than trust a copy.

    The pages are plain ES modules loaded by URL, and a browser will happily keep
    an old one. That bit during development — an edited module kept serving its
    previous version — and it would bite far harder on 28 September if we fix
    something and a judge's open tab keeps the stale copy. The files are small
    and served locally, so revalidation costs nothing.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/shared/", "/js/", "/css/", "/pages/")) or path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


install_telemetry(app)
app.include_router(router)

# The shared modules are mounted before the app's own files, because the root
# mount matches everything. Both are plain static directories: no build step, and
# the browser loads the ES modules directly.
if SHARED_DIR.exists():
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
