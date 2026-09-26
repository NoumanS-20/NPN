"""The allocation engine.

Every constraint the use case names gets its own test on a small hand-built
fixture where the right answer can be worked out on paper, plus a full-scale run
on the real offers to check it stays fast enough for a live demo.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights


def _offers(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "material_id": "M1", "plant_id": "P1", "lead_days": 30.0, "p75_lead_days": 40.0,
        "capacity_per_week": 1000.0, "moq": 0.0, "origin": "real",
        "delay_probability": 0.10, "quality_probability": 0.10,
        "contract_min_share": 0.0, "contract_max_share": 1.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _request(qty: float = 1000.0, **kwargs) -> AllocationRequest:
    options = {"max_supplier_share": 1.0, "min_suppliers_per_material": 1}
    options.update(kwargs)
    return AllocationRequest(
        requirements=[Requirement("M1", "P1", 1, qty)],
        **options,
    )


@pytest.fixture
def three_suppliers() -> pd.DataFrame:
    return _offers([
        {"supplier_id": "cheap", "supplier_name": "Cheap Co", "unit_price": 1.00,
         "delay_probability": 0.40},
        {"supplier_id": "mid", "supplier_name": "Middle Co", "unit_price": 1.20,
         "delay_probability": 0.10},
        {"supplier_id": "safe", "supplier_name": "Safe Co", "unit_price": 1.50,
         "delay_probability": 0.02},
    ])


# --- the constraints -----------------------------------------------------


def test_demand_is_met_exactly(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000), three_suppliers)
    assert result.is_optimal
    assert sum(line.qty for line in result.lines) == pytest.approx(1000, abs=1)


def test_capacity_is_never_exceeded() -> None:
    offers = _offers([
        {"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 300},
        {"supplier_id": "b", "unit_price": 2.0, "capacity_per_week": 900},
    ])
    result = solve(_request(1000), offers)
    assert result.is_optimal
    for line in result.lines:
        matching = offers.loc[offers["supplier_id"] == line.supplier_id, "capacity_per_week"]
        limit = float(matching.iloc[0])
        assert line.qty <= limit + 1


def test_minimum_order_quantity_is_respected() -> None:
    offers = _offers([
        {"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 600, "moq": 300},
        {"supplier_id": "b", "unit_price": 1.1, "capacity_per_week": 600, "moq": 300},
    ])
    result = solve(_request(1000), offers)
    assert result.is_optimal
    assert all(line.qty >= 299 for line in result.lines)


def test_concentration_cap_forces_a_split(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000, max_supplier_share=0.4), three_suppliers)
    assert result.is_optimal
    assert max(line.qty for line in result.lines) <= 401
    assert result.suppliers_used >= 3


def test_minimum_supplier_count_is_honoured(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000, min_suppliers_per_material=3), three_suppliers)
    assert result.is_optimal
    assert result.suppliers_used >= 3


def test_contract_maximum_limits_a_supplier(three_suppliers: pd.DataFrame) -> None:
    offers = three_suppliers.copy()
    offers.loc[offers["supplier_id"] == "cheap", "contract_max_share"] = 0.25
    result = solve(_request(1000), offers)
    assert result.is_optimal
    allocated = result.by_supplier().get("cheap", 0.0)
    assert allocated <= 251


def test_excluded_suppliers_receive_nothing(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000, excluded_suppliers=("cheap",)), three_suppliers)
    assert result.is_optimal
    assert "cheap" not in result.by_supplier()


# --- the behaviour that matters ------------------------------------------


def test_cost_only_weights_pick_the_cheapest(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000, weights=Weights(cost=1, risk=0, quality=0)), three_suppliers)
    assert result.by_supplier().get("cheap", 0) == pytest.approx(1000, abs=1)


def test_risk_weight_moves_volume_off_the_risky_supplier(three_suppliers: pd.DataFrame) -> None:
    """The headline behaviour: risk changes who gets the order, not just a report."""
    ignore_risk = solve(
        _request(1000, weights=Weights(cost=1, risk=0, quality=0)), three_suppliers
    )
    price_risk = solve(
        _request(1000, weights=Weights(cost=1, risk=1, quality=0)), three_suppliers
    )
    assert ignore_risk.by_supplier().get("cheap", 0) > price_risk.by_supplier().get("cheap", 0)
    assert price_risk.expected_late_units < ignore_risk.expected_late_units


def test_high_risk_share_falls_as_the_risk_weight_rises(three_suppliers: pd.DataFrame) -> None:
    low = solve(_request(1000, weights=Weights(risk=0)), three_suppliers)
    high = solve(_request(1000, weights=Weights(risk=3)), three_suppliers)
    assert high.high_risk_share <= low.high_risk_share


def test_every_line_carries_a_reason(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000, max_supplier_share=0.5), three_suppliers)
    assert result.lines
    for line in result.lines:
        assert len(line.reason) > 20
        assert line.share_of_requirement > 0


def test_costs_add_up(three_suppliers: pd.DataFrame) -> None:
    result = solve(_request(1000), three_suppliers)
    assert result.total_cost == pytest.approx(
        result.material_cost + result.risk_cost + result.quality_cost, rel=1e-6
    )


# --- failure behaviour ---------------------------------------------------


def test_impossible_demand_returns_a_status_not_an_exception() -> None:
    offers = _offers([{"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 10}])
    result = solve(_request(10_000), offers)
    assert result.status != "optimal"
    assert result.message
    assert result.lines == []


def test_no_approved_supplier_is_reported_clearly(three_suppliers: pd.DataFrame) -> None:
    request = AllocationRequest(requirements=[Requirement("UNKNOWN", "P1", 1, 100)])
    result = solve(request, three_suppliers)
    assert result.status == "infeasible"
    assert "No approved supplier" in result.message


def test_negative_weights_are_rejected(three_suppliers: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="negative"):
        solve(_request(1000, weights=Weights(risk=-1)), three_suppliers)


# --- relaxation, reported rather than silent -----------------------------


def test_cap_is_raised_when_capacity_cannot_cover_it() -> None:
    """Two suppliers cannot cover demand at a 40% cap, so the cap must give."""
    offers = _offers([
        {"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 600},
        {"supplier_id": "b", "unit_price": 1.1, "capacity_per_week": 600},
    ])
    result = solve(_request(1000, max_supplier_share=0.4), offers)
    assert result.is_optimal
    assert "concentration cap raised" in result.message


def test_contract_ceilings_are_waived_only_as_a_last_resort() -> None:
    offers = _offers([
        {"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 900,
         "contract_max_share": 0.3},
        {"supplier_id": "b", "unit_price": 1.1, "capacity_per_week": 900,
         "contract_max_share": 0.3},
    ])
    result = solve(_request(1000, max_supplier_share=0.4), offers)
    assert result.is_optimal
    assert "contract" in result.message.lower()


def test_relaxations_are_never_silent() -> None:
    offers = _offers([
        {"supplier_id": "a", "unit_price": 1.0, "capacity_per_week": 600},
        {"supplier_id": "b", "unit_price": 1.1, "capacity_per_week": 600},
    ])
    tight = solve(_request(1000, max_supplier_share=0.4), offers)
    loose = solve(_request(1000, max_supplier_share=1.0), offers)
    assert tight.message and not loose.message


# --- scale ---------------------------------------------------------------


def test_solves_a_full_size_problem_within_two_seconds() -> None:
    """The demo re-plans live, so the solve has to feel instant."""
    import numpy as np

    rng = np.random.default_rng(0)
    rows = []
    for material in range(12):
        for supplier in range(8):
            rows.append({
                "supplier_id": f"s{material}-{supplier}",
                "supplier_name": f"Supplier {material}-{supplier}",
                "material_id": f"M{material}",
                "unit_price": float(rng.uniform(0.8, 2.0)),
                "capacity_per_week": float(rng.uniform(400, 3000)),
                "moq": float(rng.uniform(10, 120)),
                "delay_probability": float(rng.uniform(0.02, 0.4)),
            })
    offers = _offers(rows)

    requirements = [
        Requirement(f"M{material}", "P1", week, 2000.0)
        for material in range(12)
        for week in range(1, 9)
    ]
    result = solve(AllocationRequest(requirements=requirements, max_supplier_share=0.4), offers)

    assert result.is_optimal
    assert result.solve_seconds < 2.0, f"solve took {result.solve_seconds}s"
    assert len(result.lines) > 100


@pytest.mark.requires_data
def test_contract_floors_never_make_a_real_slice_infeasible() -> None:
    """The regression this guards cost the cockpit its numbers.

    Contracted minimums force volume onto named suppliers. Added naively they
    made the full eight-plant plan infeasible, and the KPI endpoint reported
    zeros rather than failing loudly — so the first screen a judge sees went
    blank. Every slice the UI can ask for must still come back with a plan.
    """
    from supplyguard.optimizer.model import solve
    from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights
    from supplyguard.pipeline import load

    context = load()
    slices = {
        "all plants, 1 week": context.requirements[context.requirements["week"] <= 1],
        "all plants, 4 weeks": context.requirements[context.requirements["week"] <= 4],
        "the whole plan": context.requirements,
        "one plant, 2 weeks": context.requirements[
            (context.requirements["plant_id"] == "plant-nigeria")
            & (context.requirements["week"] <= 2)
        ],
    }

    for label, rows in slices.items():
        requirements = [
            Requirement(r.material_id, r.plant_id, int(r.week), float(r.required_qty))
            for r in rows.itertuples()
        ]
        result = solve(
            AllocationRequest(requirements=requirements, weights=Weights(1, 1, 1)),
            context.offers,
            context.risk,
        )
        assert result.status == "optimal", f"{label} is {result.status}: {result.message}"
        assert result.lines, f"{label} returned an empty plan"


@pytest.mark.requires_data
def test_honouring_contracts_costs_something_somewhere() -> None:
    """A constraint that never changes any answer is not being applied."""
    from supplyguard.optimizer.model import solve
    from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights
    from supplyguard.pipeline import load

    context = load()
    rows = context.requirements[
        (context.requirements["plant_id"] == "plant-nigeria")
        & (context.requirements["week"] <= 1)
    ]
    requirements = [
        Requirement(r.material_id, r.plant_id, int(r.week), float(r.required_qty))
        for r in rows.itertuples()
    ]

    with_contracts = solve(
        AllocationRequest(requirements=requirements, weights=Weights(1, 1, 1),
                          honour_contracts=True),
        context.offers, context.risk)
    without = solve(
        AllocationRequest(requirements=requirements, weights=Weights(1, 1, 1),
                          honour_contracts=False),
        context.offers, context.risk)

    assert with_contracts.status == without.status == "optimal"
    # Commitments cost money to honour; if they were free they were not enforced.
    assert with_contracts.total_cost > without.total_cost
