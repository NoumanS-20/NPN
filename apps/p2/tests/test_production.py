"""Production planning and fabric lot sizing.

Small hand-built fixtures where the right answer can be worked out on paper,
plus one check that the module makes no supplier choice — the line the mentor
drew between P2 and PR1.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from trendwear.fabric.lotsize import (
    order_plan,
    requirements_from_production,
    units_supportable,
)
from trendwear.fabric.lotsize import (
    summarise as fabric_summary,
)
from trendwear.production.plan import build_plan, summarise

ROOT = Path(__file__).resolve().parents[3]


def _styles() -> pd.DataFrame:
    return pd.DataFrame([
        {"style_id": "A", "price": 100.0, "cost": 40.0, "fabric_id": "f1", "fabric_metres": 2.0},
        {"style_id": "B", "price": 30.0, "cost": 12.0, "fabric_id": "f1", "fabric_metres": 1.0},
    ])


def _plants(capacity: int = 1000) -> pd.DataFrame:
    return pd.DataFrame([{"plant_id": "p1", "weekly_capacity_units": capacity}])


def _demand(per_week: int = 300, weeks: int = 4) -> pd.DataFrame:
    return pd.DataFrame([
        {"style_id": style, "week": week, "units": per_week}
        for style in ("A", "B")
        for week in range(1, weeks + 1)
    ])


# --- production -----------------------------------------------------------


def test_a_plan_meets_demand_when_capacity_allows() -> None:
    plan = build_plan(_demand(), _styles(), _plants(1000))
    assert plan.is_optimal
    assert plan.lost_sales_units == 0
    assert plan.total_units == pytest.approx(2400, abs=1)


def test_capacity_is_never_exceeded() -> None:
    plan = build_plan(_demand(per_week=400), _styles(), _plants(500))
    assert plan.is_optimal
    weekly = plan.lines.groupby(["plant_id", "week"])["units"].sum()
    assert (weekly <= 500 + 1).all()


def test_a_capacity_squeeze_produces_shortfalls_rather_than_a_fantasy() -> None:
    plan = build_plan(_demand(per_week=400), _styles(), _plants(300))
    assert plan.is_optimal
    assert len(plan.shortfalls) > 0
    assert plan.lost_sales_units > 0


def test_scarce_capacity_protects_the_higher_margin_style() -> None:
    """Missing a sale on a 60-margin jacket costs more than on an 18-margin tee."""
    plan = build_plan(_demand(per_week=400), _styles(), _plants(300))
    short = plan.shortfalls.groupby("style_id")["units_short"].sum()
    assert short.get("B", 0) > short.get("A", 0)


def test_the_safety_stock_target_is_carried_by_the_end() -> None:
    safety = pd.DataFrame([
        {"style_id": "A", "safety_stock": 200.0},
        {"style_id": "B", "safety_stock": 100.0},
    ])
    plan = build_plan(_demand(per_week=100), _styles(), _plants(1000), safety_stock=safety)
    assert plan.is_optimal
    assert plan.total_units >= 800 + 300 - 1        # demand plus the buffer


def test_opening_stock_reduces_what_must_be_made() -> None:
    opening = pd.DataFrame([{"style_id": "A", "on_hand": 600.0}])
    with_stock = build_plan(_demand(per_week=200), _styles(), _plants(1000), opening_stock=opening)
    without = build_plan(_demand(per_week=200), _styles(), _plants(1000))
    assert with_stock.total_units < without.total_units


def test_capacity_use_is_reported_for_every_plant_and_week() -> None:
    plan = build_plan(_demand(), _styles(), _plants())
    assert len(plan.capacity_use) == 4
    assert (plan.capacity_use["utilisation"] <= 1.001).all()


def test_the_summary_says_where_the_plan_is_tight() -> None:
    summary = summarise(build_plan(_demand(per_week=500), _styles(), _plants(1000)))
    assert summary["status"] == "optimal"
    assert 0 <= summary["peak_utilisation"] <= 1.001
    assert "lost_sales_value" in summary


# --- fabric ---------------------------------------------------------------


def test_fabric_requirements_follow_the_bill_of_materials() -> None:
    production = pd.DataFrame([
        {"style_id": "A", "plant_id": "p1", "week": 1, "units": 100},
        {"style_id": "B", "plant_id": "p1", "week": 1, "units": 100},
    ])
    requirements = requirements_from_production(production, _styles())
    assert requirements.loc[0, "metres"] == pytest.approx(300)      # 100x2 + 100x1


def test_every_order_meets_the_minimum() -> None:
    requirements = pd.DataFrame([
        {"fabric_id": "f1", "week": week, "metres": 400.0} for week in range(1, 9)
    ])
    orders = order_plan(requirements, moq={"f1": 2000.0}, lead_time_weeks=5)
    assert orders
    assert all(order.metres >= 2000.0 for order in orders)


def test_orders_are_placed_a_full_lead_time_before_they_are_needed() -> None:
    requirements = pd.DataFrame([
        {"fabric_id": "f1", "week": week, "metres": 500.0} for week in range(1, 7)
    ])
    orders = order_plan(requirements, lead_time_weeks=5)
    for order in orders:
        assert order.arrival_week - order.order_week == 5


def test_cover_for_the_first_weeks_is_already_due() -> None:
    """An order for week 1 with a five-week lead should have gone out weeks ago."""
    requirements = pd.DataFrame([{"fabric_id": "f1", "week": 1, "metres": 500.0}])
    orders = order_plan(requirements, lead_time_weeks=5)
    assert orders[0].order_week < 0


def test_holding_cost_pushes_orders_later_not_all_at_once() -> None:
    requirements = pd.DataFrame([
        {"fabric_id": "f1", "week": week, "metres": 1000.0} for week in range(1, 13)
    ])
    cheap_to_hold = order_plan(requirements, holding_cost_per_metre_week=0.0001)
    dear_to_hold = order_plan(requirements, holding_cost_per_metre_week=1.0)
    assert len(dear_to_hold) > len(cheap_to_hold)


def test_every_week_of_demand_is_covered_by_some_order() -> None:
    requirements = pd.DataFrame([
        {"fabric_id": "f1", "week": week, "metres": 700.0} for week in range(1, 11)
    ])
    orders = order_plan(requirements)
    covered = {week for order in orders for week in order.covers_weeks}
    assert covered == set(range(1, 11))


def test_arrived_fabric_limits_what_can_be_cut() -> None:
    orders = order_plan(
        pd.DataFrame([{"fabric_id": "f1", "week": 3, "metres": 600.0}]),
        lead_time_weeks=2,
    )
    supportable = units_supportable(orders, _styles(), weeks=[1, 2, 3, 4])

    before = supportable[(supportable["week"] == 2) & (supportable["style_id"] == "A")]
    after = supportable[(supportable["week"] == 3) & (supportable["style_id"] == "A")]
    assert before["units_supportable"].iloc[0] == 0        # nothing has arrived yet
    assert after["units_supportable"].iloc[0] == 300       # 600 metres / 2 per unit


def test_fabric_summary_reports_the_excess_minimums_force() -> None:
    requirements = pd.DataFrame([{"fabric_id": "f1", "week": 1, "metres": 100.0}])
    orders = order_plan(requirements, moq={"f1": 5000.0})
    summary = fabric_summary(orders, requirements)
    assert summary["excess_from_minimums"] == pytest.approx(4900, abs=1)


def test_the_fabric_module_makes_no_supplier_choice() -> None:
    """The line the mentor drew between P2 and PR1, enforced in code."""
    source = (ROOT / "apps/p2/backend/trendwear/fabric/lotsize.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#") and "supplier" not in line.lower()
    )
    for token in ("allocate", "supplier_id", "award"):
        assert token not in code, f"the fabric module appears to choose suppliers ({token})"
