"""When to order fabric, and how much.

The use case asks us to "optimise fabric procurement against MOQ and lead-time
constraints". That is a **lot-sizing** problem: given a requirement per week, a
minimum order quantity and a four-to-six week lead time, decide which weeks to
place an order and for how much.

This module makes **no supplier choice**. Each fabric has one named source, and
the decision here is timing and quantity only. Choosing between suppliers is
PR1's job, and the mentor ruled in writing that the two solutions must not
overlap in approach. That line is the reason this is dynamic lot sizing rather
than another allocation model.

The method is Wagner-Whitin: a dynamic programme that finds the cheapest set of
order weeks exactly, rather than a rule of thumb. It is a textbook algorithm with
one recurrence, which makes it straightforward to explain in an interview — and
it handles the real tension here, that ordering early costs holding and ordering
late is impossible because of the lead time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from trendwear.config import FABRIC_LEAD_TIME_WEEKS


@dataclass(frozen=True)
class FabricOrder:
    fabric_id: str
    order_week: int
    arrival_week: int
    metres: float
    covers_weeks: tuple[int, ...]
    cost: float


def requirements_from_production(
    production: pd.DataFrame,
    bom: pd.DataFrame,
) -> pd.DataFrame:
    """Turn a production plan into metres of fabric per week."""
    if production.empty:
        return pd.DataFrame(columns=["fabric_id", "week", "metres"])

    joined = production.merge(
        bom[["style_id", "fabric_id", "fabric_metres"]], on="style_id", how="left"
    )
    joined["metres"] = joined["units"] * joined["fabric_metres"].fillna(0)

    return (
        joined.groupby(["fabric_id", "week"], as_index=False)["metres"]
        .sum()
        .sort_values(["fabric_id", "week"])
        .reset_index(drop=True)
    )


def _wagner_whitin(
    demand: list[float],
    order_cost: float,
    holding_cost: float,
) -> list[int]:
    """Which periods to order in, minimising ordering plus holding cost.

    The classic recurrence: the cheapest plan covering periods 1..t is the
    cheapest plan covering 1..j-1 plus one order at j covering j..t. Exact, and
    small enough here to run in milliseconds.
    """
    periods = len(demand)
    if periods == 0:
        return []

    best = [math.inf] * (periods + 1)
    best[0] = 0.0
    previous = [0] * (periods + 1)

    for t in range(1, periods + 1):
        for j in range(1, t + 1):
            # One order in period j covering j..t.
            holding = sum(
                holding_cost * (k - j) * demand[k - 1] for k in range(j, t + 1)
            )
            cost = best[j - 1] + order_cost + holding
            if cost < best[t]:
                best[t] = cost
                previous[t] = j - 1

    weeks: list[int] = []
    t = periods
    while t > 0:
        start = previous[t]
        weeks.append(start)
        t = start
    return sorted(weeks)


def order_plan(
    requirements: pd.DataFrame,
    moq: dict[str, float] | None = None,
    price: dict[str, float] | None = None,
    lead_time_weeks: int = FABRIC_LEAD_TIME_WEEKS,
    order_cost: float = 450.0,
    holding_cost_per_metre_week: float = 0.02,
) -> list[FabricOrder]:
    """The fabric orders to place, by fabric.

    An order placed in week *w* arrives in week *w + lead time*, so cover for the
    early weeks of the horizon has to be ordered before the horizon starts. Those
    orders come back with a negative order week, which is not a bug: it is the
    plan telling a buyer the commitment was already due.
    """
    moq = moq or {}
    price = price or {}
    orders: list[FabricOrder] = []

    for fabric_id, group in requirements.groupby("fabric_id"):
        weeks = sorted(group["week"].unique())
        if not weeks:
            continue

        by_week = group.set_index("week")["metres"].to_dict()
        series = [float(by_week.get(week, 0.0)) for week in weeks]

        starts = _wagner_whitin(series, order_cost, holding_cost_per_metre_week)
        minimum = float(moq.get(fabric_id, 0.0))
        unit_price = float(price.get(fabric_id, 1.0))

        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(series)
            covered = list(range(start, end))
            metres = sum(series[k] for k in covered)
            if metres <= 0:
                continue

            # A mill will not cut below its minimum, so the order rounds up. The
            # excess is real inventory and the holding cost above accounts for it.
            metres = max(metres, minimum)
            arrival = weeks[start]

            orders.append(FabricOrder(
                fabric_id=str(fabric_id),
                order_week=arrival - lead_time_weeks,
                arrival_week=arrival,
                metres=round(metres, 1),
                covers_weeks=tuple(weeks[k] for k in covered),
                cost=round(metres * unit_price, 2),
            ))

    return sorted(orders, key=lambda order: (order.order_week, order.fabric_id))


def units_supportable(
    orders: list[FabricOrder],
    bom: pd.DataFrame,
    weeks: list[int],
) -> pd.DataFrame:
    """How many units each style can be cut from the fabric that has arrived.

    Feeds back into the production plan as a constraint, which is what makes the
    four-to-six week lead time bite rather than being a number on a slide.
    """
    arrivals: dict[str, float] = {}
    rows = []

    metres_per_style = bom.set_index("style_id")["fabric_metres"].to_dict()
    fabric_of_style = bom.set_index("style_id")["fabric_id"].to_dict()

    for week in weeks:
        for order in orders:
            if order.arrival_week == week:
                arrivals[order.fabric_id] = arrivals.get(order.fabric_id, 0.0) + order.metres

        for style_id, fabric_id in fabric_of_style.items():
            metres = float(metres_per_style.get(style_id, 0.0))
            if metres <= 0:
                continue
            rows.append({
                "style_id": style_id,
                "week": week,
                "units_supportable": round(arrivals.get(fabric_id, 0.0) / metres, 1),
            })

    return pd.DataFrame(rows)


def summarise(orders: list[FabricOrder], requirements: pd.DataFrame) -> dict[str, float | int]:
    if not orders:
        return {"orders": 0, "metres": 0.0, "cost": 0.0}

    metres = sum(order.metres for order in orders)
    required = float(requirements["metres"].sum()) if len(requirements) else 0.0
    return {
        "orders": len(orders),
        "fabrics": len({order.fabric_id for order in orders}),
        "metres": round(metres, 1),
        "metres_required": round(required, 1),
        "excess_from_minimums": round(max(metres - required, 0.0), 1),
        "cost": round(sum(order.cost for order in orders), 2),
        "earliest_order_week": min(order.order_week for order in orders),
        "orders_already_due": int(sum(1 for order in orders if order.order_week < 0)),
        "mean_weeks_covered": round(
            float(np.mean([len(order.covers_weeks) for order in orders])), 2
        ),
    }
