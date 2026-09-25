"""Load the two small procurement files that carry quality and disruption labels.

SCMS records whether a delivery arrived late, but nothing about whether the goods
were any good or whether the order survived at all. These two files fill that
gap, and the use case asks for both — "supplier quality and delivery performance"
and "scenario analysis for supplier disruptions".

Both are small, and one is openly synthetic. Their loaders build the same kind of
point-in-time features as the delay model so the risk modules can be compared
like for like, and `docs/data-sources.md` records what each file really is.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

_slug_re = re.compile(r"[^a-z0-9]+")

_DISRUPTED_STATUSES = ("Cancelled", "Partially Delivered")


def _slug(value: str) -> str:
    return _slug_re.sub("-", str(value).strip().lower()).strip("-")


def _trailing_rate(df: pd.DataFrame, group: str, label: str, date: str) -> pd.Series:
    """That supplier's rate over its *earlier* orders only."""
    ordered = df.sort_values(date, kind="mergesort")
    rate = ordered.groupby(group)[label].transform(lambda s: s.shift(1).expanding().mean())
    return rate.reindex(df.index)


def load_quality_orders(path: Path) -> pd.DataFrame:
    """Supplier order lines with material-discrepancy events.

    Source: "Supplier Stability Dataset for Procurement". Its own page states it
    is synthetic, simulating a semiconductor manufacturer, so results from it
    demonstrate the method rather than evidence real supplier behaviour.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run: python scripts/fetch_data.py")

    raw = pd.read_csv(path)

    df = pd.DataFrame({
        "order_id": raw["order_id"].astype(str),
        "supplier_id": ["q-" + _slug(v) for v in raw["supplier_name"]],
        "supplier_name": raw["supplier_name"].astype("string").str.strip(),
        "category": raw["component_category"].astype("string").str.strip(),
        "criticality": raw["component_criticality"].astype("string").str.strip(),
        "order_date": pd.to_datetime(raw["order_date"], errors="coerce"),
        "qty": pd.to_numeric(raw["qty_ordered"], errors="coerce").fillna(0.0),
        "unit_cost": pd.to_numeric(raw["unit_cost_usd"], errors="coerce").fillna(0.0),
        "line_spend": pd.to_numeric(raw["line_spend_usd"], errors="coerce").fillna(0.0),
        "days_late": pd.to_numeric(raw["days_late"], errors="coerce").fillna(0.0),
        "has_quality_event": raw["has_md_event"].astype(bool).astype(int),
        "supplier_fault": raw["is_supplier_fault"].notna().astype(int),
    })

    df = df.sort_values(["order_date", "order_id"], kind="mergesort").reset_index(drop=True)

    df["supplier_prior_orders"] = df.groupby("supplier_id").cumcount()
    df["supplier_prior_quality_rate"] = _trailing_rate(
        df, "supplier_id", "has_quality_event", "order_date"
    )
    df["log_qty"] = np.log1p(df["qty"].clip(lower=0))
    df["log_spend"] = np.log1p(df["line_spend"].clip(lower=0))
    df["is_critical"] = (df["criticality"] == "Critical").astype(int)
    df["is_high"] = (df["criticality"] == "High").astype(int)
    df["was_late"] = (df["days_late"] > 0).astype(int)
    df["origin"] = "public-synthetic"
    df["source"] = "supplier_order_lines"
    return df


def load_disruption_orders(path: Path) -> pd.DataFrame:
    """Purchase orders with cancellation and partial-delivery outcomes.

    Source: "Procurement KPI Analysis Dataset", whose author states it holds real
    anonymised purchase orders from 2022-23.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run: python scripts/fetch_data.py")

    raw = pd.read_csv(path)

    order_date = pd.to_datetime(raw["Order_Date"], errors="coerce")
    delivery_date = pd.to_datetime(raw["Delivery_Date"], errors="coerce")

    df = pd.DataFrame({
        "order_id": raw["PO_ID"].astype(str),
        "supplier_id": ["d-" + _slug(v) for v in raw["Supplier"]],
        "supplier_name": raw["Supplier"].astype("string").str.strip(),
        "category": raw["Item_Category"].astype("string").str.strip(),
        "order_date": order_date,
        "delivery_date": delivery_date,
        "qty": pd.to_numeric(raw["Quantity"], errors="coerce").fillna(0.0),
        "unit_price": pd.to_numeric(raw["Unit_Price"], errors="coerce").fillna(0.0),
        "negotiated_price": pd.to_numeric(raw["Negotiated_Price"], errors="coerce"),
        "defective_units": pd.to_numeric(raw["Defective_Units"], errors="coerce").fillna(0.0),
        "compliant": (raw["Compliance"].astype("string").str.strip() == "Yes").astype(int),
        "status": raw["Order_Status"].astype("string").str.strip(),
    })

    df["is_disrupted"] = df["status"].isin(_DISRUPTED_STATUSES).astype(int)
    df["promised_lead_days"] = (df["delivery_date"] - df["order_date"]).dt.days
    df["discount_pct"] = (
        1 - df["negotiated_price"] / df["unit_price"].replace(0, np.nan)
    ).fillna(0.0)

    df = df.sort_values(["order_date", "order_id"], kind="mergesort").reset_index(drop=True)

    df["supplier_prior_orders"] = df.groupby("supplier_id").cumcount()
    df["supplier_prior_disruption_rate"] = _trailing_rate(
        df, "supplier_id", "is_disrupted", "order_date"
    )
    df["log_qty"] = np.log1p(df["qty"].clip(lower=0))
    df["log_value"] = np.log1p((df["qty"] * df["unit_price"]).clip(lower=0))
    df["origin"] = "real"
    df["source"] = "procurement_kpi"
    return df


QUALITY_FEATURES = [
    "supplier_prior_orders",
    "supplier_prior_quality_rate",
    "log_qty",
    "log_spend",
    "unit_cost",
    "is_critical",
    "is_high",
    "was_late",
]

DISRUPTION_FEATURES = [
    "supplier_prior_orders",
    "supplier_prior_disruption_rate",
    "log_qty",
    "log_value",
    "unit_price",
    "discount_pct",
    "compliant",
    "promised_lead_days",
]
