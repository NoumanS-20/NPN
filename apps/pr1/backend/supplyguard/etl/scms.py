"""Load the SCMS delivery history into PR1's purchase-order table.

Source: USAID / PEPFAR health-commodity shipments, 2006-2015, 10,324 purchase
orders. This is our only tier-1 dataset, so every headline risk metric is
measured on rows produced here.

Two quirks of the file drive most of this module:

1. Date columns contain the literal strings "Date Not Captured" and
   "Pre-PO Process". Parsed naively they become 1970 timestamps and quietly
   poison every lead-time feature, so they are turned into missing values.
2. "Freight Cost (USD)" carries text such as "Freight Included in Commodity
   Cost" in roughly 40% of rows. That is information, not dirt: it means the
   freight was billed inside the item price. We record zero cost and set
   ``freight_bundled`` so the optimiser does not double-count.

A supplier is a *vendor at a manufacturing site*, because that is the unit a
buyer actually allocates to. The same vendor shipping from two factories has two
lead times, two quality records and two risk profiles.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from supplyguard.config import DATE_PLACEHOLDERS

REQUIRED_COLUMNS: set[str] = {
    "po_id", "supplier_id", "vendor", "site", "country", "product_group",
    "sub_group", "item", "molecule", "qty", "unit_price", "line_value",
    "freight_cost", "freight_bundled", "freight_known", "weight_kg", "shipment_mode",
    "po_date", "promised_date", "delivered_date", "late_days", "is_late",
    "promised_lead_days", "origin",
}

_DATE_COLUMNS = {
    "po_date": "PO Sent to Vendor Date",
    "promised_date": "Scheduled Delivery Date",
    "delivered_date": "Delivered to Client Date",
    "recorded_date": "Delivery Recorded Date",
}

_slug_re = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _slug_re.sub("-", str(value).strip().lower()).strip("-")


def _parse_dates(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    cleaned = cleaned.where(~cleaned.isin(DATE_PLACEHOLDERS))
    return pd.to_datetime(cleaned, errors="coerce", format="mixed", dayfirst=True)


def _parse_freight(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Split the freight column into a cost, a 'bundled' flag and a 'known' flag.

    40% of the rows are not numbers. They fall into three kinds, and the
    difference matters:

    * ``Freight Included in Commodity Cost`` (1,442 rows) — the freight really was
      paid, inside the item price. Cost zero, ``bundled`` true.
    * ``See DN-93 (ID#:1281)`` / ``See ASN-...`` (2,445 rows) — a cross-reference
      to another document. The cost exists somewhere we do not have.
    * ``Invoiced Separately`` (239 rows) — billed outside this record.

    Stripping non-digits would turn that first cross-reference into 931281, a
    $931k freight charge on a single line, which would wreck every cost
    comparison the optimiser makes. So we parse strictly: a value is a number
    only if it is one after removing currency punctuation.
    """
    text = series.astype("string").str.strip()
    cleaned = text.str.replace(r"[$,\s]", "", regex=True)
    numeric = pd.to_numeric(cleaned.where(cleaned.str.fullmatch(r"-?\d+(\.\d+)?")), errors="coerce")

    # Cast to numpy booleans: pandas' nullable BooleanDtype leaks into every
    # downstream mask and makes feature building awkward.
    known = numeric.notna().to_numpy(dtype=bool)
    bundled = text.str.contains(
        "Included in Commodity Cost", case=False, na=False
    ).to_numpy(dtype=bool)
    cost = numeric.fillna(0.0).astype(float).to_numpy(dtype=float)
    return (
        pd.Series(cost, index=series.index),
        pd.Series(bundled, index=series.index),
        pd.Series(known, index=series.index),
    )


def load_scms(path: Path) -> pd.DataFrame:
    """Return one tidy row per purchase order, with delivery outcome labels."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Run: python scripts/fetch_data.py"
        )

    raw = pd.read_csv(path, low_memory=False)

    df = pd.DataFrame(index=raw.index)
    df["po_id"] = raw["ID"].astype(str)
    df["vendor"] = raw["Vendor"].astype("string").str.strip()
    df["site"] = raw["Manufacturing Site"].astype("string").str.strip()
    df["supplier_id"] = [
        f"{_slug(v)}--{_slug(s)}"
        for v, s in zip(df["vendor"], df["site"], strict=True)
    ]
    df["country"] = raw["Country"].astype("string").str.strip()
    df["product_group"] = raw["Product Group"].astype("string").str.strip()
    df["sub_group"] = raw["Sub Classification"].astype("string").str.strip()
    df["item"] = raw["Item Description"].astype("string").str.strip()
    df["molecule"] = raw["Molecule/Test Type"].astype("string").str.strip()
    df["shipment_mode"] = raw["Shipment Mode"].astype("string").str.strip().fillna("Unknown")

    df["qty"] = pd.to_numeric(raw["Line Item Quantity"], errors="coerce").fillna(0).clip(lower=0)
    df["unit_price"] = pd.to_numeric(raw["Unit Price"], errors="coerce").fillna(0.0).clip(lower=0)
    df["pack_price"] = pd.to_numeric(raw["Pack Price"], errors="coerce").fillna(0.0).clip(lower=0)
    df["line_value"] = (
        pd.to_numeric(raw["Line Item Value"], errors="coerce").fillna(0.0).clip(lower=0)
    )
    df["weight_kg"] = pd.to_numeric(
        raw["Weight (Kilograms)"].astype("string").str.replace(r"[^0-9.\-]", "", regex=True),
        errors="coerce",
    ).fillna(0.0).clip(lower=0)

    df["freight_cost"], df["freight_bundled"], df["freight_known"] = _parse_freight(
        raw["Freight Cost (USD)"]
    )

    for name, column in _DATE_COLUMNS.items():
        df[name] = _parse_dates(raw[column])

    df["late_days"] = (df["delivered_date"] - df["promised_date"]).dt.days
    df["is_late"] = (df["late_days"] > 0).astype(int)
    df["promised_lead_days"] = (df["promised_date"] - df["po_date"]).dt.days

    df["origin"] = "real"
    df["source"] = "scms"

    df = df.sort_values(["promised_date", "po_id"], kind="mergesort").reset_index(drop=True)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"SCMS load is missing required columns: {sorted(missing)}")
    return df


def summarise(df: pd.DataFrame) -> dict[str, float | int | str]:
    """A few headline facts, printed by the ETL script and shown in the UI."""
    return {
        "purchase_orders": int(len(df)),
        "supplier_entities": int(df["supplier_id"].nunique()),
        "vendors": int(df["vendor"].nunique()),
        "manufacturing_sites": int(df["site"].nunique()),
        "countries": int(df["country"].nunique()),
        "items": int(df["item"].nunique()),
        "late_rate": round(float(df["is_late"].mean()), 4),
        "median_promised_lead_days": float(df["promised_lead_days"].median()),
        "freight_cost_known_rate": round(float(df["freight_known"].mean()), 4),
        "first_delivery": str(df["promised_date"].min().date()),
        "last_delivery": str(df["promised_date"].max().date()),
    }
