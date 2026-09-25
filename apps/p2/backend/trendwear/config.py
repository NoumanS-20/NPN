"""Paths and settings for TrendWear Planner (P2)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models" / "p2"

RAW_RETAIL = DATA_RAW / "retail" / "retail_store_inventory.csv"

DATABASE_PATH = DATA_PROCESSED / "trendwear.sqlite"
DATABASE_URL = os.environ.get("TRENDWEAR_DB", f"sqlite:///{DATABASE_PATH}")

SEED = 42

# Planning defaults, all overridable from the API.
FORECAST_HORIZON_WEEKS = 13
ROLLING_CYCLES = 3
SERVICE_LEVEL = 0.95
FABRIC_LEAD_TIME_WEEKS = 5
LAUNCH_CADENCE_WEEKS = 6
TARGET_STYLE_COUNT = 60

APP_NAME = "TrendWear Planner"
APP_PORT = 8002
