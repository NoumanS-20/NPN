"""The money view of a plan.

The official use-case PDF asks S&OP to synchronise "demand, supply **and
financial plans**", which our first design missed. Every plan version carries
these figures, so a cycle can be argued in the terms an executive approves in.

What is counted, and why:

* **Revenue** — consensus units at the style's price. The consensus, not the
  ambition: revenue the plants cannot supply is not revenue.
* **Gross margin** — revenue less the cost of those units.
* **Inventory value** — closing stock at cost. This is the number that makes the
  trade visible: safety stock buys service and costs working capital.
* **Distribution cost** — units through the DC-to-store lanes. Small per unit,
  and the reason a plan that looks cheap at the plant may not be.
* **Lost sales value** — demand the plan cannot meet, at margin. Not a cost in
  the accounts, but the cost of the plan, and leaving it out would make a
  shortfall look free.
"""

from __future__ import annotations

import pandas as pd


def roll_up(
    reconciliation: pd.DataFrame,
    styles: pd.DataFrame,
    production=None,
    inventory: pd.DataFrame | None = None,
    lanes: pd.DataFrame | None = None,
) -> dict[str, float]:
    """The financial summary of one plan."""
    economics = styles.set_index("style_id")

    units = reconciliation["consensus_units"]
    prices = reconciliation["style_id"].map(economics["price"]).fillna(0.0)
    costs = reconciliation["style_id"].map(economics["cost"]).fillna(0.0)

    revenue = float((units * prices).sum())
    cost_of_sales = float((units * costs).sum())
    gross_margin = revenue - cost_of_sales

    inventory_value = 0.0
    if inventory is not None and len(inventory):
        on_hand = inventory.set_index("style_id")["on_hand"]
        inventory_value = float(
            sum(
                quantity * float(economics["cost"].get(style_id, 0.0))
                for style_id, quantity in on_hand.items()
            )
        )

    distribution_cost = 0.0
    if lanes is not None and len(lanes):
        # Every unit moves through one lane; the average lane cost is the right
        # figure at plan level, before store-level allocation is decided.
        mean_lane_cost = float(lanes["cost_per_unit"].mean())
        distribution_cost = float(units.sum() * mean_lane_cost)

    lost_sales_value = 0.0
    if production is not None and getattr(production, "lost_sales_value", 0):
        lost_sales_value = float(production.lost_sales_value)

    return {
        "revenue": round(revenue, 2),
        "cost_of_sales": round(cost_of_sales, 2),
        "gross_margin": round(gross_margin, 2),
        "margin_pct": round(gross_margin / revenue, 4) if revenue else 0.0,
        "inventory_value": round(inventory_value, 2),
        "distribution_cost": round(distribution_cost, 2),
        "lost_sales_value": round(lost_sales_value, 2),
        "contribution": round(gross_margin - distribution_cost, 2),
        "units_committed": round(float(units.sum()), 1),
    }


def compare(before: dict[str, float], after: dict[str, float]) -> dict[str, dict[str, float]]:
    """What a stage did to the money."""
    keys = sorted(set(before) | set(after))
    return {
        key: {
            "before": round(float(before.get(key, 0.0)), 2),
            "after": round(float(after.get(key, 0.0)), 2),
            "change": round(float(after.get(key, 0.0)) - float(before.get(key, 0.0)), 2),
        }
        for key in keys
    }


def by_category(
    reconciliation: pd.DataFrame,
    styles: pd.DataFrame,
) -> pd.DataFrame:
    """Revenue and margin split by category, for the merchandising view."""
    # The reconciliation already carries a price column; merging the catalogue's
    # would create price_x and price_y and quietly break the arithmetic.
    joined = reconciliation.drop(columns=["price"], errors="ignore").merge(
        styles[["style_id", "category", "price", "cost", "name"]], on="style_id", how="left"
    )
    joined["revenue"] = joined["consensus_units"] * joined["price"].fillna(0)
    joined["margin"] = joined["consensus_units"] * (
        joined["price"].fillna(0) - joined["cost"].fillna(0)
    )

    return (
        joined.groupby("category", as_index=False)
        .agg(
            units=("consensus_units", "sum"),
            revenue=("revenue", "sum"),
            margin=("margin", "sum"),
            styles=("style_id", "nunique"),
        )
        .assign(margin_pct=lambda df: (df["margin"] / df["revenue"]).round(4))
        .sort_values("revenue", ascending=False)
        .reset_index(drop=True)
    )
