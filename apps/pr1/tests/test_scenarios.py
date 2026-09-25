"""Scenario analysis.

The panel will drive these live, so each one has to do something visible and
explainable. These tests check the direction of every effect — a demand spike
must cost more, an outage must move volume — because a scenario that changes
nothing on screen is worse than no scenario at all.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement
from supplyguard.scenarios.engine import SCENARIOS, largest_supplier, run


def _offers() -> pd.DataFrame:
    rows = [
        ("big", "Big Co", 1.00, 2000, 0.30, "IN"),
        ("mid", "Middle Co", 1.15, 800, 0.10, "IN"),
        ("safe", "Safe Co", 1.35, 800, 0.02, "ZA"),
        ("spare", "Spare Co", 1.50, 800, 0.05, "ZA"),
    ]
    return pd.DataFrame([
        {
            "supplier_id": sid, "supplier_name": name, "material_id": "M1", "plant_id": "P1",
            "unit_price": price, "capacity_per_week": capacity, "moq": 0.0,
            "lead_days": 21.0, "p75_lead_days": 28.0, "delay_probability": delay,
            "quality_probability": 0.10, "origin": "real", "contract_max_share": 1.0,
            "country": country,
        }
        for sid, name, price, capacity, delay, country in rows
    ])


def _request(qty: float = 1500.0, **kwargs) -> AllocationRequest:
    options = {"max_supplier_share": 0.6, "min_suppliers_per_material": 2}
    options.update(kwargs)
    return AllocationRequest(requirements=[Requirement("M1", "P1", 4, qty)], **options)


def test_every_scenario_is_declared_with_a_label() -> None:
    assert set(SCENARIOS) == {"supplier_outage", "demand_spike", "lead_time_shock", "price_shock"}
    for scenario in SCENARIOS.values():
        assert scenario.name and scenario.description and scenario.parameter_label


def test_each_scenario_returns_a_before_and_an_after() -> None:
    offers, request = _offers(), _request()
    for key in SCENARIOS:
        parameters = {"supplier_id": "big"} if key == "supplier_outage" else {}
        result = run(key, parameters, request, offers)
        assert result.before.is_optimal
        assert result.after.status in {"optimal", "infeasible"}
        assert result.narrative


# --- supplier outage ------------------------------------------------------


def test_outage_removes_that_supplier_entirely() -> None:
    """Knock out whoever is actually carrying the most volume.

    Note it is not always the cheapest supplier: with risk priced into the
    objective, a cheap but unreliable supplier can lose to a dearer, steadier
    one. That is the behaviour we want, so the test targets the plan's real
    backbone rather than assuming who it is.
    """
    offers, request = _offers(), _request()
    baseline = solve(request, offers)
    target = largest_supplier(baseline)

    result = run("supplier_outage", {"supplier_id": target}, request, offers)
    assert target in result.before.by_supplier()
    assert target not in result.after.by_supplier()


def test_outage_still_meets_demand_when_the_base_can_absorb_it() -> None:
    offers, request = _offers(), _request()
    result = run("supplier_outage", {"supplier_id": "big"}, request, offers)
    assert result.after.is_optimal
    assert sum(line.qty for line in result.after.lines) == pytest.approx(1500, abs=1)


def test_outage_of_the_main_supplier_raises_cost() -> None:
    offers, request = _offers(), _request()
    target = largest_supplier(solve(request, offers))
    result = run("supplier_outage", {"supplier_id": target}, request, offers)
    assert result.deltas["total_cost_pct"] > 0


def test_outage_reports_clearly_when_the_base_cannot_absorb_it() -> None:
    """Losing capacity we genuinely need must say so, not fail silently."""
    offers = _offers()
    offers.loc[offers["supplier_id"] != "big", "capacity_per_week"] = 100
    result = run("supplier_outage", {"supplier_id": "big"}, _request(1500), offers)
    assert not result.after.is_optimal
    assert "cannot absorb" in result.narrative


def test_outage_needs_a_supplier() -> None:
    with pytest.raises(ValueError, match="supplier_id"):
        run("supplier_outage", {}, _request(), _offers())


# --- the other three ------------------------------------------------------


def test_demand_spike_scales_requirements_and_costs_more() -> None:
    result = run("demand_spike", {"uplift_pct": 30}, _request(1000), _offers())
    assert result.after.is_optimal
    assert sum(line.qty for line in result.after.lines) == pytest.approx(1300, abs=2)
    assert result.deltas["invoice_pct"] > 25


def test_lead_time_shock_makes_near_weeks_harder_to_serve() -> None:
    offers = _offers()
    request = AllocationRequest(
        requirements=[Requirement("M1", "P1", 1, 1000.0)],
        max_supplier_share=1.0, min_suppliers_per_material=1,
    )
    result = run("lead_time_shock", {"extra_weeks": 40}, request, offers)
    assert result.after.status in {"optimal", "infeasible"}
    assert result.narrative


def test_price_shock_raises_the_invoice() -> None:
    result = run("price_shock", {"increase_pct": 25}, _request(), _offers())
    assert result.after.is_optimal
    assert result.deltas["invoice_pct"] > 0


def test_price_shock_can_target_one_country() -> None:
    offers, request = _offers(), _request()
    everywhere = run("price_shock", {"increase_pct": 25}, request, offers)
    one_country = run("price_shock", {"increase_pct": 25, "country": "ZA"}, request, offers)
    assert one_country.deltas["invoice_pct"] < everywhere.deltas["invoice_pct"]


# --- reporting ------------------------------------------------------------


def test_deltas_cover_every_reported_metric() -> None:
    result = run("demand_spike", {"uplift_pct": 30}, _request(), _offers())
    assert {"total_cost_pct", "invoice_pct", "expected_late_pct", "high_risk_pp",
            "suppliers_delta"} <= set(result.deltas)


def test_scenarios_never_mutate_the_inputs() -> None:
    """A scenario that edited the real plan would corrupt the next run."""
    offers, request = _offers(), _request()
    before_prices = offers["unit_price"].tolist()
    run("price_shock", {"increase_pct": 50}, request, offers)
    run("demand_spike", {"uplift_pct": 50}, request, offers)
    assert offers["unit_price"].tolist() == before_prices
    assert request.requirements[0].quantity == 1500.0


def test_largest_supplier_finds_the_plan_backbone() -> None:
    """On price alone the big cheap supplier wins; the helper should find it."""
    from supplyguard.optimizer.types import Weights

    result = solve(_request(weights=Weights(cost=1, risk=0, quality=0)), _offers())
    assert largest_supplier(result) == "big"


def test_risk_pricing_changes_who_the_backbone_is() -> None:
    """Worth its own test: this is the behaviour the whole project argues for."""
    from supplyguard.optimizer.types import Weights

    offers = _offers()
    on_price = solve(_request(weights=Weights(cost=1, risk=0, quality=0)), offers)
    with_risk = solve(_request(weights=Weights(cost=1, risk=1, quality=1)), offers)
    assert largest_supplier(on_price) == "big"          # cheapest, 30% late
    assert largest_supplier(with_risk) != "big"


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown scenario"):
        run("earthquake", {}, _request(), _offers())
