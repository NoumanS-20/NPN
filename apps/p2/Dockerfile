# TrendWear Planner (P2) — one image, no build step, nothing trained here.
#
# Build from the repository root:
#
#     docker build -f apps/p2/Dockerfile -t trendwear .
#     docker run -p 7860:7860 trendwear
#
# Port 7860 is the Hugging Face Spaces default, so the same image runs locally
# and hosted with no change.
#
# This image contains no part of the other application: separate code, separate
# processed tables, separate model directory. That is the mentor's ruling held
# at the container boundary, and a test in the repository checks it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# LightGBM and XGBoost are compiled against the GNU OpenMP runtime, and
# python:3.12-slim does not ship it. Without this the image builds cleanly and
# then dies on import with "libgomp.so.1: cannot open shared object file",
# which reads as an application bug rather than a missing system library.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY packages/ packages/

COPY apps/p2/backend/ apps/p2/backend/
COPY apps/p2/web/ apps/p2/web/

# The demo pack: the processed S&OP tables and the fitted demand model.
COPY data/processed/p2-v1/ data/processed/p2-v1/
COPY models/p2/ models/p2/

ENV PYTHONPATH=/app/packages:/app/apps/p2/backend

EXPOSE 7860

# The probe has to follow the same $PORT the CMD does. Hardcoding 7860 made the
# container report itself unhealthy forever on any host that injects a port,
# which reads as "build succeeded, deploy failed" and says nothing about why.
# start-period is 90s because startup loads the planning cache and warms the
# headline figures before it can answer anything.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','7860')+'/api/health')"

# Shell form on purpose: Cloud Run injects its own $PORT and the exec form
# would pass the literal string. 7860 stays the default, so the same image
# runs unchanged on Hugging Face Spaces and locally.
CMD uvicorn trendwear.main:app --host 0.0.0.0 --port ${PORT:-7860}
