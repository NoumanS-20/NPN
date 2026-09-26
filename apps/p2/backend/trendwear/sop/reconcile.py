"""Put three plans beside each other and agree one number.

This is what an S&OP cycle is for, and it is the outcome the use case names
first: "reconcile merchandising forecasts with plant capacity and fabric lead
times".

Three numbers exist for every style and week, and they rarely agree:

* **The merchandising plan** — what the buyers intend to sell. It is a
  commercial ambition, and it is usually above the forecast, because a buyer who
  plans for the statistical average has already given up on the season.
* **The statistical forecast** — what the data expects, from the demand model.
* **The constrained supply plan** — what the plants can actually make, after
  capacity and fabric lead times.

The gap between the first and the third is the conversation the whole cycle
exists to have. This module measures it in units and in money, and records the
**consensus**: the single number the business commits to, defaulting to what
supply can deliver and editable at the Pre-S&OP stage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trendwear.config import SEED

RECONCILIATION_COLUMNS: set[str] = {
    "style_id", "week", "merch_units", "forecast_units", "supply_units",
    "gap_units", "gap_value", "consensus_units", "consensus_source",
}


def build_merchandising_plan(
    forecast: pd.DataFrame,
    styles: pd.DataFrame,
    seed: int = SEED,
) -> pd.DataFrame:
    """The buyers' intent: the forecast, shifted by commercial ambition.

    Not in any dataset, and it has to exist or there is nothing to reconcile. It
    is derived as the statistical forecast times a per-style ambition factor,
    drawn once and held steady for a style so a buyer's optimism is consistent
    across the season rather than random noise week to week.

    Ambition averages about +12%, which is what makes the reconciliation screen
    show a real gap rather than three lines on top of each other.
    """
    rng = np.random.default_rng(seed + 7)

    ambition = pd.Series(
        rng.normal(1.12, 0.14, len(styles)).clip(0.85, 1.6),
        index=styles["style_id"].to_numpy(),
    )

    plan = forecast.copy()
    plan["ambition_factor"] = plan["style_id"].map(ambition).fillna(1.12).round(3)
    plan["merch_units"] = (plan["forecast_units"] * plan["ambition_factor"]).round(1)
    return plan[["style_id", "week", "merch_units", "ambition_factor"]]


def build(
    merch_plan: pd.DataFrame,
    forecast: pd.DataFrame,
    supply_plan: pd.DataFrame,
    styles: pd.DataFrame,
) -> pd.DataFrame:
    """The three plans side by side, with the gap priced."""
    merged = (
        merch_plan.merge(forecast, on=["style_id", "week"], how="outer")
        .merge(supply_plan, on=["style_id", "week"], how="outer")
        .fillna({"merch_units": 0.0, "forecast_units": 0.0, "supply_units": 0.0})
    )

    prices = styles.set_index("style_id")["price"]
    merged["price"] = merged["style_id"].map(prices).fillna(0.0)

    merged["gap_units"] = (merged["merch_units"] - merged["supply_units"]).round(1)
    merged["gap_value"] = (merged["gap_units"] * merged["price"]).round(2)

    # The consensus cannot promise more than the plants can make. Pre-S&OP may
    # lower it; it may not raise it above supply, which is the discipline the
    # meeting exists to enforce.
    merged["consensus_units"] = np.minimum(merged["merch_units"], merged["supply_units"]).round(1)
    merged["consensus_source"] = np.where(
        merged["merch_units"] <= merged["supply_units"], "merchandising", "supply"
    )

    missing = RECONCILIATION_COLUMNS - set(merged.columns)
    if missing:
        raise ValueError(f"reconciliation is missing columns: {sorted(missing)}")
    return merged.sort_values(["style_id", "week"]).reset_index(drop=True)


def override_consensus(
    reconciliation: pd.DataFrame,
    style_id: str,
    week: int,
    units: float,
) -> pd.DataFrame:
    """Set an agreed number by hand, as Pre-S&OP would.

    The override is capped at what supply can deliver. A meeting can decide to
    sell less than the plants can make; it cannot decide to sell more.
    """
    out = reconciliation.copy()
    mask = (out["style_id"] == style_id) & (out["week"] == week)
    if not mask.any():
        raise KeyError(f"no reconciliation row for {style_id!r} in week {week}")

    supply = float(out.loc[mask, "supply_units"].iloc[0])
    agreed = min(float(units), supply)

    out.loc[mask, "consensus_units"] = round(agreed, 1)
    out.loc[mask, "consensus_source"] = "agreed"
    if agreed < units:
        out.loc[mask, "consensus_source"] = "agreed (capped at supply)"
    return out


def summarise(reconciliation: pd.DataFrame) -> dict[str, float | int]:
    short = reconciliation[reconciliation["gap_units"] > 0]
    return {
        "rows": int(len(reconciliation)),
        "styles": int(reconciliation["style_id"].nunique()),
        "merch_units": round(float(reconciliation["merch_units"].sum()), 1),
        "forecast_units": round(float(reconciliation["forecast_units"].sum()), 1),
        "supply_units": round(float(reconciliation["supply_units"].sum()), 1),
        "consensus_units": round(float(reconciliation["consensus_units"].sum()), 1),
        "gap_units": round(float(short["gap_units"].sum()), 1),
        "gap_value": round(float(short["gap_value"].sum()), 2),
        "styles_short": int(short["style_id"].nunique()),
        "ambition_vs_forecast_pct": round(
            (
                reconciliation["merch_units"].sum() / reconciliation["forecast_units"].sum() - 1
            ) * 100,
            2,
        ) if reconciliation["forecast_units"].sum() else 0.0,
    }


def biggest_gaps(
    reconciliation: pd.DataFrame, styles: pd.DataFrame, limit: int = 10
) -> pd.DataFrame:
    """Where the argument in the meeting will be, in order."""
    by_style = (
        reconciliation.groupby("style_id")
        .agg(
            merch_units=("merch_units", "sum"),
            supply_units=("supply_units", "sum"),
            gap_units=("gap_units", "sum"),
            gap_value=("gap_value", "sum"),
        )
        .reset_index()
    )
    named = by_style.merge(styles[["style_id", "name", "category"]], on="style_id", how="left")
    return named.sort_values("gap_value", ascending=False).head(limit).reset_index(drop=True)
