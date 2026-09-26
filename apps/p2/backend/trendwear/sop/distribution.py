"""When production actually reaches a shop floor.

The use case lists "DC-to-store transportation and lead-time data" as an input,
and the reason it matters is simple: a unit made in week 6 is not a unit on sale
in week 6. It has to move, and the move takes time.

This module turns a production plan into store availability by week, which is
what the Logistics view shows and what makes a lane's transit time a planning
fact rather than a number in a table.
"""

from __future__ import annotations

import math

import pandas as pd


def store_availability(
    production: pd.DataFrame,
    lanes: pd.DataFrame,
    stores: pd.DataFrame,
) -> pd.DataFrame:
    """When each store can sell what each plant made.

    Production is split across stores in equal shares — allocation by store
    demand is a separate decision, and not one the use case asks us to make.
    """
    if production.empty or lanes.empty:
        return pd.DataFrame(
            columns=[
                "style_id", "store_id", "week_produced", "week_available",
                "transit_days", "units", "distribution_cost",
            ]
        )

    lane_lookup = lanes.set_index("store_id")
    store_ids = list(stores["store_id"])
    share = 1 / max(len(store_ids), 1)

    rows = []
    for line in production.itertuples():
        for store_id in store_ids:
            lane = lane_lookup.loc[store_id]
            transit_days = float(lane["transit_days"])
            transit_weeks = math.ceil(transit_days / 7)
            units = float(line.units) * share

            rows.append({
                "style_id": line.style_id,
                "store_id": store_id,
                "dc_id": lane["dc_id"],
                "week_produced": int(line.week),
                "week_available": int(line.week) + transit_weeks,
                "transit_days": transit_days,
                "transit_weeks": transit_weeks,
                "units": round(units, 1),
                "distribution_cost": round(units * float(lane["cost_per_unit"]), 2),
            })

    return pd.DataFrame(rows)


def late_to_store(availability: pd.DataFrame, demand: pd.DataFrame) -> pd.DataFrame:
    """Units that arrive after the week they were wanted in.

    This is the cost of transit made visible: production can be on time and the
    shelf still empty.
    """
    if availability.empty:
        return availability

    wanted = demand.groupby(["style_id", "week"], as_index=False)["units"].sum()
    wanted = wanted.rename(columns={"week": "week_wanted", "units": "units_wanted"})

    arrivals = (
        availability.groupby(["style_id", "week_available"], as_index=False)["units"].sum()
        .rename(columns={"week_available": "week_wanted", "units": "units_arriving"})
    )

    merged = wanted.merge(arrivals, on=["style_id", "week_wanted"], how="left").fillna(
        {"units_arriving": 0.0}
    )
    merged["shortfall"] = (merged["units_wanted"] - merged["units_arriving"]).clip(lower=0).round(1)
    return merged[merged["shortfall"] > 0].reset_index(drop=True)


def summarise(availability: pd.DataFrame) -> dict[str, float | int]:
    if availability.empty:
        return {"rows": 0, "distribution_cost": 0.0}

    return {
        "rows": int(len(availability)),
        "stores": int(availability["store_id"].nunique()),
        "units": round(float(availability["units"].sum()), 1),
        "distribution_cost": round(float(availability["distribution_cost"].sum()), 2),
        "mean_transit_days": round(float(availability["transit_days"].mean()), 1),
        "slowest_lane_days": float(availability["transit_days"].max()),
        "mean_weeks_to_shelf": round(float(availability["transit_weeks"].mean()), 2),
    }
