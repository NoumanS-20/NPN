"""Reconciliation, the rolling cycle, distribution and the money view.

The reconciliation tests guard the discipline the meeting exists to enforce: a
consensus may be lower than what the plants can make, never higher.
"""

from __future__ import annotations

import pandas as pd
import pytest
from trendwear.sop.cycle import (
    STAGES,
    Cycle,
    advance,
    compare_versions,
    history,
    next_stage,
    reject,
    run_rolling,
)
from trendwear.sop.distribution import late_to_store, store_availability
from trendwear.sop.financials import by_category, roll_up
from trendwear.sop.reconcile import (
    biggest_gaps,
    build,
    build_merchandising_plan,
    override_consensus,
    summarise,
)


def _styles() -> pd.DataFrame:
    return pd.DataFrame([
        {"style_id": "A", "name": "Harbour Tee", "category": "Tee", "price": 50.0, "cost": 20.0},
        {"style_id": "B", "name": "Atlas Coat", "category": "Jacket", "price": 200.0, "cost": 90.0},
    ])


def _forecast() -> pd.DataFrame:
    return pd.DataFrame([
        {"style_id": "A", "week": 1, "forecast_units": 1000.0},
        {"style_id": "B", "week": 1, "forecast_units": 200.0},
    ])


def _supply(a: float = 900.0, b: float = 300.0) -> pd.DataFrame:
    return pd.DataFrame([
        {"style_id": "A", "week": 1, "supply_units": a},
        {"style_id": "B", "week": 1, "supply_units": b},
    ])


# --- reconciliation -------------------------------------------------------


def test_merchandising_plans_above_the_forecast() -> None:
    """A buyer who plans for the statistical average has given up on the season."""
    plan = build_merchandising_plan(_forecast(), _styles())
    assert (plan["merch_units"] > 0).all()
    assert plan["ambition_factor"].mean() > 1.0


def test_ambition_is_steady_for_a_style_not_random_each_week() -> None:
    forecast = pd.DataFrame([
        {"style_id": "A", "week": week, "forecast_units": 1000.0} for week in range(1, 6)
    ])
    plan = build_merchandising_plan(forecast, _styles())
    assert plan[plan["style_id"] == "A"]["ambition_factor"].nunique() == 1


def test_the_three_plans_sit_side_by_side_with_the_gap_priced() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())

    assert {"merch_units", "forecast_units", "supply_units", "gap_units", "gap_value"} <= set(
        reconciliation.columns
    )
    row = reconciliation[reconciliation["style_id"] == "A"].iloc[0]
    assert row["gap_units"] == pytest.approx(row["merch_units"] - row["supply_units"], abs=0.1)
    assert row["gap_value"] == pytest.approx(row["gap_units"] * 50.0, abs=0.5)


def test_the_consensus_never_promises_more_than_supply() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())
    assert (reconciliation["consensus_units"] <= reconciliation["supply_units"] + 0.01).all()


def test_the_consensus_follows_merchandising_when_supply_allows() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(a=99_999, b=99_999), _styles())
    assert (reconciliation["consensus_source"] == "merchandising").all()


def test_a_meeting_can_agree_less_but_not_more() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())

    lowered = override_consensus(reconciliation, "A", 1, 500)
    assert lowered.loc[lowered["style_id"] == "A", "consensus_units"].iloc[0] == 500

    raised = override_consensus(reconciliation, "A", 1, 5000)
    row = raised[raised["style_id"] == "A"].iloc[0]
    assert row["consensus_units"] == 900              # capped at supply
    assert "capped" in row["consensus_source"]


def test_an_unknown_row_cannot_be_overridden() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())
    with pytest.raises(KeyError):
        override_consensus(reconciliation, "NOPE", 1, 100)


def test_the_summary_reports_the_shortfall_in_money() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    result = summarise(build(merch, _forecast(), _supply(), _styles()))
    assert result["gap_value"] > 0
    assert result["styles_short"] >= 1
    assert result["ambition_vs_forecast_pct"] > 0


def test_the_biggest_gaps_lead_with_money_not_units() -> None:
    """A 100-unit gap on a coat matters more than a 300-unit gap on a tee."""
    merch = pd.DataFrame([
        {"style_id": "A", "week": 1, "merch_units": 1200.0, "ambition_factor": 1.2},
        {"style_id": "B", "week": 1, "merch_units": 300.0, "ambition_factor": 1.5},
    ])
    reconciliation = build(merch, _forecast(), _supply(a=900, b=100), _styles())
    gaps = biggest_gaps(reconciliation, _styles())

    # A is 300 units short at 50 each; B is 200 short at 200 each. Money leads.
    assert gaps.iloc[0]["style_id"] == "B"


# --- the rolling cycle ----------------------------------------------------


def test_a_rolling_process_creates_one_cycle_per_month() -> None:
    cycles = run_rolling(months=3, horizon_weeks=13)
    assert len(cycles) == 3
    assert [cycle.month for cycle in cycles] == [1, 2, 3]


def test_each_cycle_starts_later_and_plans_the_same_horizon() -> None:
    cycles = run_rolling(months=3, horizon_weeks=13, weeks_per_month=4)
    assert cycles[1].start_week > cycles[0].start_week
    assert {cycle.horizon_weeks for cycle in cycles} == {13}
    assert cycles[0].end_week == cycles[0].start_week + 12


def test_stages_run_in_order() -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    for expected in STAGES:
        version = advance(cycle, {"revenue": 100.0})
        assert version.stage == expected
    assert cycle.is_approved


def test_a_stage_cannot_be_skipped() -> None:
    assert next_stage("demand_review") == "supply_review"
    assert next_stage("executive_approval") is None
    with pytest.raises(ValueError):
        next_stage("imaginary_stage")


def test_an_approved_cycle_cannot_advance_again() -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    for _ in STAGES:
        advance(cycle, {"revenue": 1.0})
    with pytest.raises(ValueError, match="already approved"):
        advance(cycle, {"revenue": 1.0})


def test_rejection_sends_the_plan_back_one_stage_with_a_reason() -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    advance(cycle, {"revenue": 1.0})
    advance(cycle, {"revenue": 1.0})
    assert cycle.stage == "supply_review"

    version = reject(cycle, "capacity assumptions look optimistic")
    assert cycle.stage == "demand_review"
    assert "Rejected" in version.note


def test_the_first_stage_has_nowhere_to_go_back_to() -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    advance(cycle, {"revenue": 1.0})
    with pytest.raises(ValueError, match="first stage"):
        reject(cycle, "no")


def test_versions_are_immutable_snapshots() -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    metrics = {"revenue": 100.0}
    version = advance(cycle, metrics)

    metrics["revenue"] = 999.0                  # the caller's dict moves on
    assert version.metrics["revenue"] == 100.0  # the stored version does not


def test_two_versions_can_be_compared(  ) -> None:
    cycle = Cycle(month=1, start_week=1, horizon_weeks=13)
    first = advance(cycle, {"revenue": 100.0, "margin": 40.0})
    second = advance(cycle, {"revenue": 120.0, "margin": 44.0})

    comparison = compare_versions(first, second)
    assert comparison["revenue"]["change"] == 20.0
    assert comparison["revenue"]["change_pct"] == 20.0


def test_history_covers_every_cycle() -> None:
    cycles = run_rolling(months=2)
    for cycle in cycles:
        advance(cycle, {"revenue": 10.0})
        advance(cycle, {"revenue": 12.0})

    table = history(cycles)
    assert len(table) == 4
    assert set(table["cycle_month"]) == {1, 2}


# --- distribution ---------------------------------------------------------


def _lanes() -> pd.DataFrame:
    return pd.DataFrame([
        {"dc_id": "dc-north", "store_id": "S001", "transit_days": 3, "cost_per_unit": 0.57},
        {"dc_id": "dc-south", "store_id": "S002", "transit_days": 14, "cost_per_unit": 1.01},
    ])


def _stores() -> pd.DataFrame:
    return pd.DataFrame([
        {"store_id": "S001", "region": "North", "dc_id": "dc-north"},
        {"store_id": "S002", "region": "South", "dc_id": "dc-south"},
    ])


def test_transit_pushes_stock_into_a_later_week() -> None:
    """A unit made in week 6 is not a unit on sale in week 6."""
    production = pd.DataFrame([{"style_id": "A", "plant_id": "p1", "week": 6, "units": 1000}])
    availability = store_availability(production, _lanes(), _stores())

    near = availability[availability["store_id"] == "S001"].iloc[0]
    far = availability[availability["store_id"] == "S002"].iloc[0]
    assert near["week_available"] == 7          # 3 days, one week
    assert far["week_available"] == 8           # 14 days, two weeks


def test_distribution_cost_follows_the_lane() -> None:
    production = pd.DataFrame([{"style_id": "A", "plant_id": "p1", "week": 1, "units": 1000}])
    availability = store_availability(production, _lanes(), _stores())
    assert availability["distribution_cost"].sum() > 0

    near = availability[availability["store_id"] == "S001"]["distribution_cost"].iloc[0]
    far = availability[availability["store_id"] == "S002"]["distribution_cost"].iloc[0]
    assert far > near


def test_stock_that_arrives_late_is_reported() -> None:
    production = pd.DataFrame([{"style_id": "A", "plant_id": "p1", "week": 6, "units": 1000}])
    availability = store_availability(production, _lanes(), _stores())
    demand = pd.DataFrame([{"style_id": "A", "week": 6, "units": 800}])

    late = late_to_store(availability, demand)
    assert len(late) == 1
    assert late.iloc[0]["shortfall"] == 800     # nothing has reached a shelf in week 6


def test_an_empty_plan_produces_an_empty_schedule() -> None:
    empty = store_availability(pd.DataFrame(), _lanes(), _stores())
    assert empty.empty


# --- financials -----------------------------------------------------------


def test_the_money_view_covers_what_the_use_case_asks_for() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())
    money = roll_up(reconciliation, _styles(), lanes=_lanes())

    assert {"revenue", "gross_margin", "margin_pct", "inventory_value",
            "distribution_cost", "lost_sales_value"} <= set(money)
    assert money["revenue"] > 0
    assert 0 < money["margin_pct"] < 1


def test_revenue_counts_the_consensus_not_the_ambition() -> None:
    """Revenue the plants cannot supply is not revenue."""
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(a=100, b=100), _styles())
    money = roll_up(reconciliation, _styles())

    ambition_revenue = float((merch["merch_units"] * 50).sum())
    assert money["revenue"] < ambition_revenue


def test_inventory_is_valued_at_cost() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())
    inventory = pd.DataFrame([{"style_id": "A", "on_hand": 100.0}])

    money = roll_up(reconciliation, _styles(), inventory=inventory)
    assert money["inventory_value"] == pytest.approx(2000.0)     # 100 x cost 20


def test_categories_are_reported_separately_for_merchandising() -> None:
    merch = build_merchandising_plan(_forecast(), _styles())
    reconciliation = build(merch, _forecast(), _supply(), _styles())
    split = by_category(reconciliation, _styles())

    assert set(split["category"]) == {"Tee", "Jacket"}
    assert (split["margin_pct"] > 0).all()
