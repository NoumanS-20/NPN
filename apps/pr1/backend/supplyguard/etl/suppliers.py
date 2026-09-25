"""Build the supplier catalogue: one row per supplier entity.

This is the table the buyer sorts on screen and the table the optimiser chooses
from. It combines two very different populations, and keeps the difference
visible rather than blending them:

* **217 supplier entities with real trading history** (SCMS). Their on-time rate,
  lead time, price and volume are measured from orders they actually delivered.
* **~2,590 vendors from the SAP master.** We have no trading history with them,
  so their performance columns are unknown, ``has_history`` is false, and the
  risk model must fall back on group-level priors rather than inventing numbers.

Calling an unknown supplier "95% on time" would be the easiest way to make the
demo look good and the interview go badly, so the catalogue refuses to guess.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from supplyguard.etl.sap import load_vendor_master

CATALOGUE_COLUMNS: set[str] = {
    "supplier_id", "name", "country", "product_group", "orders", "on_time_rate",
    "avg_lead_days", "p75_lead_days", "lead_observations", "lead_days_source",
    "defect_rate", "avg_unit_price", "historical_volume", "historical_value",
    "has_history", "origin", "source",
}


def _primary(series: pd.Series) -> str:
    """The most frequent value, used to label a supplier's main product group."""
    counts = series.value_counts()
    return str(counts.index[0]) if len(counts) else "UNKNOWN"


MIN_LEAD_OBSERVATIONS = 3


def _lead_time_hierarchy(catalogue: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Fill lead times from the most specific evidence available.

    Only 38% of SCMS rows carry a purchase-order date, so a promised lead time
    can be computed for 3,925 orders across 155 of the 217 suppliers, and only
    65 suppliers have five or more observations.

    Rather than paper over that with one global average, we fall back in steps
    and record which step each supplier landed on. The steps matter because the
    product groups genuinely differ: ARV runs about 130 days, HRDT 92, MRDT 63.
    A single global number would have flattened exactly the differences the
    optimiser is meant to trade off.
    """
    usable = orders[orders["promised_lead_days"] > 0]
    group_median = usable.groupby("product_group")["promised_lead_days"].median()
    global_median = float(usable["promised_lead_days"].median())

    enough = catalogue["lead_observations"] >= MIN_LEAD_OBSERVATIONS
    source = pd.Series("supplier", index=catalogue.index)

    from_group = catalogue["product_group"].map(group_median)
    use_group = ~enough & from_group.notna()
    use_global = ~enough & ~from_group.notna()

    catalogue.loc[use_group, "avg_lead_days"] = from_group[use_group]
    catalogue.loc[use_group, "p75_lead_days"] = from_group[use_group] * 1.25
    catalogue.loc[use_global, "avg_lead_days"] = global_median
    catalogue.loc[use_global, "p75_lead_days"] = global_median * 1.25

    source[use_group] = "group"
    source[use_global] = "global"
    catalogue["lead_days_source"] = source

    # A supplier with observations but no p75 (a single order) still needs one.
    catalogue["p75_lead_days"] = catalogue["p75_lead_days"].fillna(
        catalogue["avg_lead_days"] * 1.25
    )
    catalogue["avg_lead_days"] = catalogue["avg_lead_days"].fillna(global_median)
    return catalogue


def _from_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Per-supplier statistics measured from real delivered orders."""
    lead = orders["promised_lead_days"]
    working = orders.assign(_lead=lead.where(lead > 0))

    grouped = working.groupby("supplier_id")
    catalogue = pd.DataFrame({
        "orders": grouped.size(),
        "on_time_rate": 1 - grouped["is_late"].mean(),
        "avg_lead_days": grouped["_lead"].median(),
        "p75_lead_days": grouped["_lead"].quantile(0.75),
        "lead_observations": grouped["_lead"].count(),
        "avg_unit_price": grouped["unit_price"].mean(),
        "historical_volume": grouped["qty"].sum(),
        "historical_value": grouped["line_value"].sum(),
        "countries_served": grouped["country"].nunique(),
        "name": grouped["vendor"].first().astype(str) + " — " + grouped["site"].first().astype(str),
        "country": grouped["country"].agg(_primary),
        "product_group": grouped["product_group"].agg(_primary),
    }).reset_index()

    catalogue = _lead_time_hierarchy(catalogue, orders)

    catalogue["defect_rate"] = np.nan          # SCMS records no quality outcome
    catalogue["has_history"] = True
    catalogue["origin"] = "real"
    catalogue["source"] = "scms"
    return catalogue


def _from_sap(sap_dir: Path, exclude: set[str]) -> pd.DataFrame:
    """The wider vendor list, with performance left explicitly unknown."""
    vendors = load_vendor_master(sap_dir)
    vendors = vendors[~vendors["supplier_id"].isin(exclude)].copy()

    vendors["product_group"] = "UNCLASSIFIED"
    vendors["orders"] = 0
    vendors["lead_observations"] = 0
    vendors["lead_days_source"] = "none"
    for column in (
        "on_time_rate", "avg_lead_days", "p75_lead_days", "defect_rate",
        "avg_unit_price", "historical_volume", "historical_value",
    ):
        vendors[column] = np.nan
    vendors["countries_served"] = 1
    vendors["has_history"] = False
    return vendors


def build_catalogue(orders: pd.DataFrame, sap_dir: Path | None = None) -> pd.DataFrame:
    """Combine measured suppliers with the wider ERP vendor master."""
    traded = _from_orders(orders)

    frames = [traded]
    if sap_dir is not None:
        frames.append(_from_sap(sap_dir, exclude=set(traded["supplier_id"])))

    catalogue = pd.concat(frames, ignore_index=True, sort=False)
    catalogue = catalogue.sort_values(
        ["source", "supplier_id"], kind="mergesort"
    ).reset_index(drop=True)

    missing = CATALOGUE_COLUMNS - set(catalogue.columns)
    if missing:
        raise ValueError(f"catalogue is missing columns: {sorted(missing)}")
    return catalogue


def summarise(catalogue: pd.DataFrame) -> dict[str, float | int]:
    measured = catalogue[catalogue["has_history"]]
    return {
        "suppliers_total": int(len(catalogue)),
        "suppliers_with_history": int(len(measured)),
        "median_on_time_rate": round(float(measured["on_time_rate"].median()), 4),
        "worst_on_time_rate": round(float(measured["on_time_rate"].min()), 4),
        "median_lead_days": float(measured["avg_lead_days"].median()),
        "lead_from_own_history": int((measured["lead_days_source"] == "supplier").sum()),
        "lead_from_group": int((measured["lead_days_source"] == "group").sum()),
        "lead_from_global": int((measured["lead_days_source"] == "global").sum()),
        "product_groups": int(measured["product_group"].nunique()),
    }
