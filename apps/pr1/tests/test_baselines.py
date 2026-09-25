"""Baselines — the alternatives our plan is measured against.

These tests guard the honesty of the savings claim as much as the code. A
baseline that quietly fails to meet demand, or that is handicapped, would make
the optimiser look better than it is, and that is exactly the kind of number a
panel will pull apart.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.optimizer.baselines import (
    cheapest_first,
    compare,
    equal_split,
    historical_mix,
    run_all,
)
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights


def _offers() -> pd.DataFrame:
    return pd.DataFrame([
        {"supplier_id": "cheap", "supplier_name": "Cheap Co", "material_id": "M1",
         "plant_id": "P1", "unit_price": 1.00, "capacity_per_week": 600, "moq": 0.0,
         "lead_days": 30.0, "p75_lead_days": 40.0, "delay_probability": 0.40,
         "quality_probability": 0.10, "origin": "real", "contract_max_share": 1.0},
        {"supplier_id": "mid", "supplier_name": "Middle Co", "material_id": "M1",
         "plant_id": "P1", "unit_price": 1.20, "capacity_per_week": 600, "moq": 0.0,
         "lead_days": 30.0, "p75_lead_days": 40.0, "delay_probability": 0.10,
         "quality_probability": 0.10, "origin": "real", "contract_max_share": 1.0},
        {"supplier_id": "safe", "supplier_name": "Safe Co", "material_id": "M1",
         "plant_id": "P1", "unit_price": 1.40, "capacity_per_week": 600, "moq": 0.0,
         "lead_days": 30.0, "p75_lead_days": 40.0, "delay_probability": 0.02,
         "quality_probability": 0.10, "origin": "real", "contract_max_share": 1.0},
    ])


def _history() -> pd.DataFrame:
    return pd.DataFrame({
        "item": ["M1"] * 3,
        "supplier_id": ["cheap", "mid", "safe"],
        "qty": [800.0, 150.0, 50.0],
    })


def _request(qty: float = 1000.0, **kwargs) -> AllocationRequest:
    options = {"max_supplier_share": 1.0, "min_suppliers_per_material": 1}
    options.update(kwargs)
    return AllocationRequest(requirements=[Requirement("M1", "P1", 1, qty)], **options)


# --- each baseline is a fair comparison ----------------------------------


@pytest.mark.parametrize("name", ["cheapest_first", "equal_split", "historical_mix"])
def test_every_baseline_meets_demand(name: str) -> None:
    results = run_all(_request(1000), _offers(), _history())
    total = sum(line.qty for line in results[name].lines)
    assert total == pytest.approx(1000, abs=1), f"{name} left demand unmet"


@pytest.mark.parametrize("name", ["cheapest_first", "equal_split", "historical_mix"])
def test_no_baseline_exceeds_capacity(name: str) -> None:
    offers = _offers()
    results = run_all(_request(1000), offers, _history())
    for line in results[name].lines:
        matching = offers.loc[offers["supplier_id"] == line.supplier_id, "capacity_per_week"]
        assert line.qty <= float(matching.iloc[0]) + 1


def test_cheapest_first_really_is_cheapest_on_invoice() -> None:
    """If our plan beat it on invoice cost, the baseline would be broken."""
    offers = _offers()
    request = _request(1000)
    plan = solve(request, offers)
    baseline = cheapest_first(request, offers)
    assert baseline.material_cost <= plan.material_cost + 1e-6


def test_equal_split_spreads_evenly_when_capacity_allows() -> None:
    result = equal_split(_request(900), _offers())
    quantities = sorted(result.by_supplier().values())
    assert quantities == pytest.approx([300, 300, 300], abs=1)


def test_historical_mix_follows_past_proportions() -> None:
    result = historical_mix(_request(1000), _offers(), _history())
    allocation = result.by_supplier()
    assert allocation["cheap"] > allocation["mid"] > allocation["safe"]


# --- the comparison ------------------------------------------------------


def test_comparison_reports_every_metric() -> None:
    offers, history = _offers(), _history()
    request = _request(1000, weights=Weights(cost=1, risk=1, quality=1))
    plan = solve(request, offers)
    results = compare(plan, run_all(request, offers, history))

    assert set(results) == {"cheapest_first", "equal_split", "historical_mix"}
    for metrics in results.values():
        assert {"invoice_delta_pct", "total_cost_delta_pct", "expected_late_delta_pct",
                "high_risk_delta_pp"} <= set(metrics)


def test_the_plan_reduces_expected_lateness_against_cheapest_first() -> None:
    """The claim the whole project rests on."""
    offers, history = _offers(), _history()
    request = _request(1000, weights=Weights(cost=1, risk=1, quality=1))
    plan = solve(request, offers)
    results = compare(plan, run_all(request, offers, history))
    assert results["cheapest_first"]["expected_late_delta_pct"] < 0


def test_the_plan_wins_on_total_cost_even_where_it_loses_on_invoice() -> None:
    offers, history = _offers(), _history()
    request = _request(1000, weights=Weights(cost=1, risk=1, quality=1))
    plan = solve(request, offers)
    results = compare(plan, run_all(request, offers, history))
    cheapest = results["cheapest_first"]
    assert cheapest["invoice_delta_pct"] >= 0          # we pay more on paper
    assert cheapest["total_cost_delta_pct"] < 0        # and less once risk is priced


def test_comparison_survives_an_empty_baseline() -> None:
    empty = solve(AllocationRequest(requirements=[Requirement("UNKNOWN", "P1", 1, 10)]), _offers())
    results = compare(solve(_request(1000), _offers()), {"broken": empty})
    assert results["broken"]["status"] != "optimal"
