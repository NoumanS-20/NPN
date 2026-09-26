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

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:7860/api/health')"

CMD ["uvicorn", "trendwear.main:app", "--host", "0.0.0.0", "--port", "7860"]
