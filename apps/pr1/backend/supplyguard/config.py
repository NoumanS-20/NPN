"""Paths and tunable settings for SupplyGuard.

One place for every filename and constant, so pointing the application at a
different dataset is a config change rather than a code change.
"""

from __future__ import annotations

import os
from pathlib import Path

# repo root: apps/pr1/backend/supplyguard/config.py -> up five levels
ROOT = Path(__file__).resolve().parents[4]

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models" / "pr1"

RAW_SCMS = DATA_RAW / "scms" / "SCMS_Delivery_History_Dataset.csv"
RAW_SAP_DIR = DATA_RAW / "sap"
RAW_PROCUREMENT_KPI = DATA_RAW / "procurement" / "procurement_kpi.csv"
RAW_SUPPLIER_LINES = DATA_RAW / "procurement" / "supplier_order_lines.csv"
RAW_SUPPLY_CHAIN = DATA_RAW / "procurement" / "supply_chain_data.csv"

DATABASE_PATH = DATA_PROCESSED / "supplyguard.sqlite"
DATABASE_URL = os.environ.get("SUPPLYGUARD_DB", f"sqlite:///{DATABASE_PATH}")

# One seed for the whole application. Demo runs must be reproducible.
SEED = 42

# Planning defaults, all overridable from the API.
PLANNING_HORIZON_WEEKS = 8
TARGET_SUPPLIER_COUNT = 520
MAX_SUPPLIER_SHARE = 0.40
MIN_SUPPLIERS_PER_MATERIAL = 2
TOP_PLANTS = 8

# How far ahead procurement plans, in weeks. Risk-adjusted lead times in this
# data cluster around 23 weeks with a tail past 30, which is normal for
# international pharmaceutical supply.
#
# The value has to be chosen, not guessed. At 26 weeks the base plan is
# infeasible; at 34 a +2-week shock changes nothing. At 30 the plan is feasible,
# a two-week shock costs 0.24%, and a six-week shock genuinely breaks it — so the
# scenario shows a real cliff rather than a number that nudges.
#
# An earlier version added 52 weeks of slack here to dodge infeasibility, which
# meant lead time never bound and the lead-time scenario moved nothing at all.
LEAD_TIME_ALLOWANCE_WEEKS = 30

# Values the file uses in date columns to mean "no date".
DATE_PLACEHOLDERS = ("Date Not Captured", "Pre-PO Process", "N/A", "NA", "")

APP_NAME = "SupplyGuard"
APP_PORT = 8001
