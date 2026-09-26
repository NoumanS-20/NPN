# SupplyGuard (PR1) — one image, no build step, nothing trained here.
#
# Build from the repository root, because the image needs the shared packages
# and the pre-built demo pack as well as this application:
#
#     docker build -f apps/pr1/Dockerfile -t supplyguard .
#     docker run -p 7860:7860 supplyguard
#
# Port 7860 is the Hugging Face Spaces default, so the same image runs locally
# and hosted with no change.
#
# Build the demo pack first (scripts/build_demo_pack.py). The processed tables
# and the fitted models are copied in, and the container starts in seconds
# because it only reads them. If one is missing the application says so at
# startup and names the command that fixes it, rather than quietly training a
# model inside a container.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall XGBoost.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# The shared library: metrics, time helpers, logging, telemetry, and the shared
# CSS and JavaScript the pages import from /shared.
COPY packages/ packages/

COPY apps/pr1/backend/ apps/pr1/backend/
COPY apps/pr1/web/ apps/pr1/web/

# The demo pack: the processed planning tables and the three fitted risk models.
COPY data/processed/pr1-v1/ data/processed/pr1-v1/
COPY models/pr1/ models/pr1/

ENV PYTHONPATH=/app/packages:/app/apps/pr1/backend

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:7860/api/health')"

# Shell form on purpose: Cloud Run injects its own $PORT and the exec form
# would pass the literal string. 7860 stays the default, so the same image
# runs unchanged on Hugging Face Spaces and locally.
CMD uvicorn supplyguard.main:app --host 0.0.0.0 --port ${PORT:-7860}
