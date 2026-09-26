"""Safety stock and the inventory position.

Step 5 of the mentor's P2 flow, and the step our first design missed. A plan
without safety stock is the first thing an experienced planner would question:
it implicitly assumes the forecast is right, and forecasts are never right.

The formula is the standard one:

    safety stock = z x sigma(forecast error) x sqrt(lead time in weeks)

* **sigma is measured, not assumed.** It is the standard deviation of this
  style's own forecast residuals over the test period, so a style we predict
  well carries less buffer than one we predict badly. That is the whole point:
  safety stock is the price of forecast error.
* **The square root** is there because errors over several weeks partly cancel.
  Multiplying by the lead time instead would roughly double the buffer for a
  five-week lead and tie up stock that is not needed.
* **z comes from the service level** — 1.645 at 95%, the level a fashion
  retailer would typically hold for a core line.

A style with no residual history gets the population's typical error rather than
zero, because "we have never measured this" is not the same as "this never goes
wrong".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from trendwear.config import FABRIC_LEAD_TIME_WEEKS, SERVICE_LEVEL

POSITION_COLUMNS: set[str] = {
    "style_id", "on_hand", "mean_weekly_demand", "sigma_error", "safety_stock",
    "reorder_point", "target_stock", "weeks_of_cover", "gap_units", "flag",
}

# Cover below this many weeks is a stock-out waiting to happen; above this
# multiple of the target, capital is sitting on a shelf.
_STOCKOUT_WEEKS = 1.0
_OVERSTOCK_MULTIPLE = 2.0


def z_for(service_level: float) -> float:
    """The safety factor for a service level, from the normal distribution."""
    if not 0 < service_level < 1:
        raise ValueError("service level must sit between 0 and 1")
    return float(norm.ppf(service_level))


def compute(
    residuals: pd.DataFrame,
    lead_time_weeks: float = FABRIC_LEAD_TIME_WEEKS,
    service_level: float = SERVICE_LEVEL,
) -> pd.DataFrame:
    """Safety stock per style from its own forecast error.

    ``residuals`` needs ``style_id`` and ``error`` (actual minus forecast).
    """
    if lead_time_weeks <= 0:
        raise ValueError("lead time must be positive")

    z = z_for(service_level)

    by_style = residuals.groupby("style_id")["error"].agg(
        sigma_error=lambda s: float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        observations="size",
    )

    # A style we have never scored inherits the population's typical error:
    # unmeasured is not the same as reliable.
    population_sigma = float(by_style.loc[by_style["observations"] > 1, "sigma_error"].median())
    if not np.isfinite(population_sigma):
        population_sigma = 0.0
    by_style["sigma_error"] = by_style["sigma_error"].where(
        by_style["observations"] > 1, population_sigma
    )

    by_style["service_level"] = service_level
    by_style["z"] = z
    by_style["lead_time_weeks"] = lead_time_weeks
    by_style["safety_stock"] = (
        z * by_style["sigma_error"] * np.sqrt(lead_time_weeks)
    ).round(1)

    return by_style.reset_index()


def reorder_point(
    mean_weekly_demand: float, lead_time_weeks: float, safety_stock: float
) -> float:
    """Demand over the lead time, plus the buffer."""
    return round(mean_weekly_demand * lead_time_weeks + safety_stock, 1)


def build_position(
    weekly: pd.DataFrame,
    safety: pd.DataFrame,
    forecast: pd.DataFrame | None = None,
    lead_time_weeks: float = FABRIC_LEAD_TIME_WEEKS,
) -> pd.DataFrame:
    """Where every style stands: stock on hand against what it needs."""
    latest = weekly.sort_values("week_index").groupby("style_id").tail(1)
    on_hand = latest.set_index("style_id")["inventory"]

    if forecast is not None and len(forecast):
        demand = forecast.groupby("style_id")["forecast_units"].mean()
    else:
        recent = weekly[weekly["week_index"] >= weekly["week_index"].max() - 12]
        demand = recent.groupby("style_id")["units"].mean()

    position = safety.copy()
    position["on_hand"] = position["style_id"].map(on_hand).fillna(0.0)
    position["mean_weekly_demand"] = position["style_id"].map(demand).fillna(0.0)

    position["reorder_point"] = [
        reorder_point(row.mean_weekly_demand, lead_time_weeks, row.safety_stock)
        for row in position.itertuples()
    ]
    position["target_stock"] = (
        position["mean_weekly_demand"] * lead_time_weeks + position["safety_stock"]
    ).round(1)
    position["weeks_of_cover"] = np.where(
        position["mean_weekly_demand"] > 0,
        (position["on_hand"] / position["mean_weekly_demand"]).round(2),
        np.inf,
    )
    position["gap_units"] = (position["target_stock"] - position["on_hand"]).round(1)
    position["flag"] = [_flag(row) for row in position.itertuples()]

    missing = POSITION_COLUMNS - set(position.columns)
    if missing:
        raise ValueError(f"inventory position is missing columns: {sorted(missing)}")
    return position.sort_values("gap_units", ascending=False).reset_index(drop=True)


def _flag(row) -> str:
    if row.on_hand <= 0 or row.weeks_of_cover < _STOCKOUT_WEEKS:
        return "stockout_risk"
    if row.on_hand < row.reorder_point:
        return "below_reorder"
    if row.target_stock > 0 and row.on_hand > row.target_stock * _OVERSTOCK_MULTIPLE:
        return "overstock"
    return "healthy"


def backtest(
    weekly: pd.DataFrame,
    safety: pd.DataFrame,
    lead_time_weeks: float = FABRIC_LEAD_TIME_WEEKS,
) -> dict[str, float | int]:
    """Check the buffer against what actually happened.

    For each style, how often did a week's demand exceed the mean plus the
    buffer? At a 95% service level that should happen in roughly one week in
    twenty. Reporting it against the real series is the difference between a
    formula and a claim.
    """
    buffers = safety.set_index("style_id")["safety_stock"]
    means = weekly.groupby("style_id")["units"].mean()

    breaches = 0
    observed = 0
    for style_id, group in weekly.groupby("style_id"):
        covered = means.get(style_id, 0.0) + buffers.get(style_id, 0.0)
        breaches += int((group["units"] > covered).sum())
        observed += len(group)

    rate = breaches / observed if observed else 0.0
    return {
        "weeks_observed": int(observed),
        "weeks_demand_exceeded_cover": int(breaches),
        "breach_rate": round(rate, 4),
        "implied_service_level": round(1 - rate, 4),
        "stock_held": round(float(buffers.sum()), 1),
    }


def summarise(position: pd.DataFrame) -> dict[str, float | int]:
    counts = position["flag"].value_counts()
    return {
        "styles": int(len(position)),
        "stockout_risk": int(counts.get("stockout_risk", 0)),
        "below_reorder": int(counts.get("below_reorder", 0)),
        "healthy": int(counts.get("healthy", 0)),
        "overstock": int(counts.get("overstock", 0)),
        "total_safety_stock": round(float(position["safety_stock"].sum()), 1),
        "median_weeks_of_cover": round(
            float(position.loc[np.isfinite(position["weeks_of_cover"]), "weeks_of_cover"].median()),
            2,
        ),
        "units_short_of_target": round(
            float(position.loc[position["gap_units"] > 0, "gap_units"].sum()), 1
        ),
    }
