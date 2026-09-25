"""Build the material requirement plan that the allocation engine consumes.

The official data spec lists a "material demand forecast (by SKU/plant)" as an
input to PR1. We produce it by rolling historical consumption forward with a
seasonal index — **deliberately not a trained forecaster**.

Why deliberately: the mentor ruled in writing that P2 and PR1 must not overlap in
approach, and demand forecasting is P2's core method. PR1's contribution is the
sourcing decision, and its requirement plan is an *input* a buyer can override on
screen, exactly as an MRP run would hand one over in a real system.
``apps/pr1/tests/test_requirements.py`` fails the build if a forecasting library
ever appears in this application.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from supplyguard.etl.plants import attach_plant_id

# Materials below this share of a plant's volume are noise for planning purposes:
# they produce single-order requirements no supplier would quote against.
_MIN_MATERIAL_SHARE = 0.01
_MAX_MATERIALS_PER_PLANT = 6


def _weekly_consumption(orders: pd.DataFrame) -> pd.DataFrame:
    """Average units per week for each material and plant."""
    dated = orders.dropna(subset=["promised_date", "plant_id"])
    span_weeks = max(
        (dated["promised_date"].max() - dated["promised_date"].min()).days / 7.0, 1.0
    )
    totals = dated.groupby(["item", "plant_id"], as_index=False)["qty"].sum()
    totals["weekly_qty"] = totals["qty"] / span_weeks
    return totals.rename(columns={"item": "material_id"})


def _seasonal_index(orders: pd.DataFrame) -> pd.Series:
    """Index by week-of-year, normalised to average 1.0.

    Procurement volume is lumpy, so the index is smoothed and clipped: it should
    shape the plan, not create spikes no supplier could serve.
    """
    dated = orders.dropna(subset=["promised_date"])
    by_week = dated.groupby(dated["promised_date"].dt.isocalendar().week)["qty"].sum()
    index = by_week / by_week.mean()
    smoothed = index.rolling(5, center=True, min_periods=1).mean()
    return smoothed.clip(0.6, 1.6)


def build_plan(
    orders: pd.DataFrame,
    plants: pd.DataFrame,
    horizon_weeks: int = 8,
    seasonal: bool = True,
    start_week: int = 1,
) -> pd.DataFrame:
    """Return required quantity per material, plant and week.

    Only materials that matter to a plant are planned: a material must account
    for at least 1% of that plant's volume, and each plant plans its six largest.
    That keeps the optimisation a real decision rather than hundreds of
    single-unit lines.
    """
    tagged = attach_plant_id(orders, plants)
    consumption = _weekly_consumption(tagged)

    plant_totals = consumption.groupby("plant_id")["weekly_qty"].transform("sum")
    consumption["share"] = consumption["weekly_qty"] / plant_totals
    consumption = consumption[consumption["share"] >= _MIN_MATERIAL_SHARE]
    consumption = (
        consumption.sort_values(["plant_id", "weekly_qty"], ascending=[True, False])
        .groupby("plant_id")
        .head(_MAX_MATERIALS_PER_PLANT)
    )

    index = _seasonal_index(orders) if seasonal else None

    weeks = np.arange(start_week, start_week + horizon_weeks)
    rows = consumption.merge(pd.DataFrame({"week": weeks}), how="cross")

    if index is not None:
        factor = rows["week"].map(lambda w: float(index.get(((w - 1) % 52) + 1, 1.0)))
    else:
        factor = pd.Series(1.0, index=rows.index)

    rows["required_qty"] = (rows["weekly_qty"] * factor).round().clip(lower=1)
    rows["source"] = "derived"

    columns = ["material_id", "plant_id", "week", "required_qty", "source"]
    return (
        rows[columns]
        .sort_values(["plant_id", "material_id", "week"], kind="mergesort")
        .reset_index(drop=True)
    )


def summarise(plan: pd.DataFrame) -> dict[str, float | int]:
    return {
        "lines": int(len(plan)),
        "materials": int(plan["material_id"].nunique()),
        "plants": int(plan["plant_id"].nunique()),
        "weeks": int(plan["week"].nunique()),
        "total_units": float(plan["required_qty"].sum()),
        "median_weekly_line": float(plan["required_qty"].median()),
    }
