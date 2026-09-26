"""Capacity-constrained production planning.

"Reconcile merchandising forecasts with plant capacity" is the first outcome the
use case asks for, and this is the half that says what the plants can actually
make.

A linear programme over style, plant and week. Decide how many units of each
style each plant makes each week, to meet demand plus the safety-stock target,
without exceeding weekly capacity and without running ahead of fabric.

The objective prices the three ways a plan can be wrong:

* **lost sales** — demand we cannot meet, at the style's own margin, because
  missing a sale on a £90 jacket costs more than missing one on a £20 tee;
* **holding** — building early and sitting on stock;
* **production cost** — a small term, so the plan does not build for its own sake.

Lost sales are priced highest. A planner will accept holding cost to protect a
sale, and the objective should say so rather than leaving it to a weight nobody
can explain.

Deliberately **not** here: choosing a supplier. Fabric comes from a single named
source under a minimum order quantity and a lead time. Supplier choice belongs
to PR1, and the mentor ruled the two approaches must not overlap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import pulp

# What each failure costs, as a multiple of the style's own unit margin.
LOST_SALE_MULTIPLE = 1.0
HOLDING_COST_PER_UNIT_WEEK = 0.04      # a fraction of unit cost
PRODUCTION_PENALTY = 0.001             # breaks ties towards making later


@dataclass(frozen=True)
class ProductionPlan:
    lines: pd.DataFrame
    shortfalls: pd.DataFrame
    capacity_use: pd.DataFrame
    status: str
    total_units: float
    lost_sales_units: float
    lost_sales_value: float
    holding_cost: float
    solve_seconds: float
    message: str = ""

    @property
    def is_optimal(self) -> bool:
        return self.status == "optimal"


def build_plan(
    demand: pd.DataFrame,
    styles: pd.DataFrame,
    plants: pd.DataFrame,
    safety_stock: pd.DataFrame | None = None,
    fabric_available: pd.DataFrame | None = None,
    opening_stock: pd.DataFrame | None = None,
) -> ProductionPlan:
    """Plan production across plants and weeks.

    ``demand`` needs style_id, week, units. ``styles`` needs style_id, price,
    cost. ``plants`` needs plant_id, weekly_capacity_units.
    """
    started = time.perf_counter()

    weeks = sorted(demand["week"].unique())
    style_ids = sorted(demand["style_id"].unique())
    plant_ids = list(plants["plant_id"])

    economics = styles.set_index("style_id")
    capacity = plants.set_index("plant_id")["weekly_capacity_units"].to_dict()
    demand_lookup = demand.set_index(["style_id", "week"])["units"].to_dict()

    buffer = (
        safety_stock.set_index("style_id")["safety_stock"].to_dict()
        if safety_stock is not None
        else {}
    )
    opening = (
        opening_stock.set_index("style_id")["on_hand"].to_dict()
        if opening_stock is not None
        else {}
    )
    fabric_cap = (
        fabric_available.set_index(["style_id", "week"])["units_supportable"].to_dict()
        if fabric_available is not None
        else {}
    )

    problem = pulp.LpProblem("production_plan", pulp.LpMinimize)

    make = {
        (style, plant, week): pulp.LpVariable(f"m_{s}_{p}_{week}", lowBound=0)
        for s, style in enumerate(style_ids)
        for p, plant in enumerate(plant_ids)
        for week in weeks
    }
    unmet = {
        (style, week): pulp.LpVariable(f"u_{s}_{week}", lowBound=0)
        for s, style in enumerate(style_ids)
        for week in weeks
    }
    stock = {
        (style, week): pulp.LpVariable(f"i_{s}_{week}", lowBound=0)
        for s, style in enumerate(style_ids)
        for week in weeks
    }

    objective = []
    for style in style_ids:
        price = float(economics.loc[style, "price"]) if style in economics.index else 40.0
        cost = float(economics.loc[style, "cost"]) if style in economics.index else 20.0
        margin = max(price - cost, 1.0)

        for week in weeks:
            objective.append(LOST_SALE_MULTIPLE * margin * unmet[(style, week)])
            objective.append(HOLDING_COST_PER_UNIT_WEEK * cost * stock[(style, week)])
            for plant in plant_ids:
                objective.append(PRODUCTION_PENALTY * cost * make[(style, plant, week)])

    problem += pulp.lpSum(objective)

    # Stock balance: what we had, plus what we made, less what we sold.
    for style in style_ids:
        for index, week in enumerate(weeks):
            wanted = float(demand_lookup.get((style, week), 0.0))
            made = pulp.lpSum(make[(style, plant, week)] for plant in plant_ids)
            previous = (
                stock[(style, weeks[index - 1])]
                if index
                else float(opening.get(style, 0.0))
            )
            problem += (
                stock[(style, week)] == previous + made - (wanted - unmet[(style, week)]),
                f"balance_{style}_{week}",
            )

        # Carry the safety-stock target by the end of the horizon rather than
        # every week: forcing it from week one would demand a build the plants
        # cannot do and would make the whole plan look infeasible.
        target = float(buffer.get(style, 0.0))
        if target > 0:
            problem += (stock[(style, weeks[-1])] >= target, f"buffer_{style}")

    # Weekly capacity per plant.
    for plant in plant_ids:
        for week in weeks:
            problem += (
                pulp.lpSum(make[(style, plant, week)] for style in style_ids)
                <= float(capacity.get(plant, 0.0)),
                f"capacity_{plant}_{week}",
            )

    # Fabric limits what can be cut, where a fabric plan says so.
    for (style, week), supportable in fabric_cap.items():
        if style in style_ids and week in weeks:
            problem += (
                pulp.lpSum(make[(style, plant, week)] for plant in plant_ids) <= supportable,
                f"fabric_{style}_{week}",
            )

    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[problem.status].lower()

    if status != "optimal":
        return ProductionPlan(
            lines=pd.DataFrame(), shortfalls=pd.DataFrame(), capacity_use=pd.DataFrame(),
            status=status, total_units=0.0, lost_sales_units=0.0, lost_sales_value=0.0,
            holding_cost=0.0, solve_seconds=time.perf_counter() - started,
            message="No production plan satisfies capacity and the safety-stock target.",
        )

    rows = []
    for (style, plant, week), variable in make.items():
        quantity = float(variable.value() or 0.0)
        if quantity > 0.5:
            rows.append({
                "style_id": style, "plant_id": plant, "week": week,
                "units": round(quantity, 1),
            })

    shortfall_rows = []
    lost_units = lost_value = 0.0
    for (style, week), variable in unmet.items():
        quantity = float(variable.value() or 0.0)
        if quantity > 0.5:
            price = float(economics.loc[style, "price"]) if style in economics.index else 40.0
            cost = float(economics.loc[style, "cost"]) if style in economics.index else 20.0
            value = quantity * (price - cost)
            lost_units += quantity
            lost_value += value
            shortfall_rows.append({
                "style_id": style, "week": week, "units_short": round(quantity, 1),
                "margin_lost": round(value, 2),
                "demand": round(float(demand_lookup.get((style, week), 0.0)), 1),
            })

    holding = sum(
        HOLDING_COST_PER_UNIT_WEEK
        * (float(economics.loc[style, "cost"]) if style in economics.index else 20.0)
        * float(stock[(style, week)].value() or 0.0)
        for style in style_ids
        for week in weeks
    )

    lines = pd.DataFrame(rows)
    use_rows = []
    for plant in plant_ids:
        for week in weeks:
            used = (
                lines[(lines["plant_id"] == plant) & (lines["week"] == week)]["units"].sum()
                if len(lines)
                else 0.0
            )
            limit = float(capacity.get(plant, 0.0))
            use_rows.append({
                "plant_id": plant, "week": week, "units": round(used, 1),
                "capacity": limit,
                "utilisation": round(used / limit, 4) if limit else 0.0,
            })

    return ProductionPlan(
        lines=lines,
        shortfalls=pd.DataFrame(shortfall_rows),
        capacity_use=pd.DataFrame(use_rows),
        status="optimal",
        total_units=round(float(lines["units"].sum()) if len(lines) else 0.0, 1),
        lost_sales_units=round(lost_units, 1),
        lost_sales_value=round(lost_value, 2),
        holding_cost=round(holding, 2),
        solve_seconds=round(time.perf_counter() - started, 3),
    )


def summarise(plan: ProductionPlan) -> dict[str, float | int | str]:
    if not plan.is_optimal:
        return {"status": plan.status, "message": plan.message}

    use = plan.capacity_use
    return {
        "status": plan.status,
        "units_planned": plan.total_units,
        "styles": int(plan.lines["style_id"].nunique()) if len(plan.lines) else 0,
        "weeks": int(plan.lines["week"].nunique()) if len(plan.lines) else 0,
        "lost_sales_units": plan.lost_sales_units,
        "lost_sales_value": plan.lost_sales_value,
        "holding_cost": plan.holding_cost,
        "peak_utilisation": round(float(use["utilisation"].max()), 4) if len(use) else 0.0,
        "mean_utilisation": round(float(use["utilisation"].mean()), 4) if len(use) else 0.0,
        "weeks_at_capacity": int((use["utilisation"] > 0.98).sum()) if len(use) else 0,
        "solve_seconds": plan.solve_seconds,
    }
