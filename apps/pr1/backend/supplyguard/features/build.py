"""Point-in-time features for supplier risk.

Everything here obeys one rule: **a feature for an order may only use orders that
came before it.** A trailing late rate that includes the order being scored is
the fastest way to produce a model with excellent test metrics and no predictive
value, and it is the first thing an interviewer will probe.

Mechanically that means `groupby(...).shift(1)` and expanding windows over rows
sorted by promised date, never a plain `groupby().mean()`.

The features fall into three groups:

* **Supplier history** — how this supplier has performed for us so far. Missing
  for a supplier's first order, which is honest: we knew nothing then either.
* **This order** — size, value, weight, promised lead time, shipment mode.
* **Context** — season and destination, which carry real signal in this data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS: set[str] = {
    "supplier_prior_orders",
    "supplier_prior_late_rate",
    "supplier_prior_avg_delay",
    "supplier_prior_volume",
    "order_size_vs_supplier_median",
    "promised_lead_days",
    "log_qty",
    "log_line_value",
    "weight_per_unit",
    "freight_per_unit",
    "week_of_year",
    "destination_prior_orders",
    "destination_prior_late_rate",
    "is_arv",
    "is_hrdt",
    "mode_air",
    "mode_ocean",
    "mode_truck",
    "mode_air_charter",
}

_MODES = {
    "mode_air": "Air",
    "mode_ocean": "Ocean",
    "mode_truck": "Truck",
    "mode_air_charter": "Air Charter",
}

# Measured signal, not assumed. Late rates by destination run from 24.9% (Congo,
# DRC) down to 0.9% (Vietnam); by product group, ARV 12.5% against HRDT 6.5%; by
# shipment mode, Ocean 17.5% and Truck 16.1% against Air 9.6%.
#
# A quarter-of-the-year flag was tried and dropped: late rates are 12.8, 10.3,
# 12.5 and 10.2 per cent across the four quarters, which is noise. Shipping a
# feature that carries no signal invites a question we cannot answer well.


def build_order_features(orders: pd.DataFrame) -> pd.DataFrame:
    """Return ``orders`` with model features attached, in the original row order.

    The frame is sorted by promised date internally so trailing windows are
    correct, then restored, so callers can rely on row alignment.
    """
    df = orders.copy()
    df["_row"] = np.arange(len(df))
    df = df.sort_values(["promised_date", "po_id"], kind="mergesort")

    grouped = df.groupby("supplier_id", sort=False)

    # shift(1) is what keeps the current order out of its own history.
    df["supplier_prior_orders"] = grouped.cumcount()
    df["supplier_prior_late_rate"] = grouped["is_late"].transform(
        lambda s: s.shift(1).expanding().mean()
    )
    df["supplier_prior_avg_delay"] = grouped["late_days"].transform(
        lambda s: s.shift(1).expanding().mean()
    )
    df["supplier_prior_volume"] = grouped["qty"].transform(lambda s: s.shift(1).expanding().sum())

    prior_median_qty = grouped["qty"].transform(lambda s: s.shift(1).expanding().median())
    df["order_size_vs_supplier_median"] = (df["qty"] / prior_median_qty).replace(
        [np.inf, -np.inf], np.nan
    )

    df["log_qty"] = np.log1p(df["qty"].clip(lower=0))
    df["log_line_value"] = np.log1p(df["line_value"].clip(lower=0))
    df["weight_per_unit"] = (df["weight_kg"] / df["qty"].replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )

    freight = df["freight_cost"].where(df.get("freight_known", True), np.nan)
    df["freight_per_unit"] = (freight / df["qty"].replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )

    df["week_of_year"] = df["promised_date"].dt.isocalendar().week.astype("float")

    # Destination history, built exactly like supplier history: this order's own
    # outcome is shifted out before the expanding mean.
    by_destination = df.groupby("country", sort=False)
    df["destination_prior_orders"] = by_destination.cumcount()
    df["destination_prior_late_rate"] = by_destination["is_late"].transform(
        lambda s: s.shift(1).expanding().mean()
    )

    group = df["product_group"].astype("string").fillna("UNKNOWN")
    df["is_arv"] = (group == "ARV").astype(int)
    df["is_hrdt"] = (group == "HRDT").astype(int)

    mode = df["shipment_mode"].astype("string").fillna("Unknown")
    for column, label in _MODES.items():
        df[column] = (mode == label).astype(int)

    df = df.sort_values("_row", kind="mergesort").drop(columns="_row").reset_index(drop=True)

    missing = FEATURE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"feature build is missing columns: {sorted(missing)}")
    return df


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """The model input, in a stable column order.

    Missing values are left in place: gradient-boosted trees handle them
    natively, and "this supplier has no history with us" is information worth
    keeping rather than a zero to be imputed.
    """
    return df[sorted(FEATURE_COLUMNS)].astype(float)


def coverage(df: pd.DataFrame) -> dict[str, float]:
    """How much of each feature is actually populated — quoted in the model guide."""
    return {
        column: round(float(df[column].notna().mean()), 4) for column in sorted(FEATURE_COLUMNS)
    }
