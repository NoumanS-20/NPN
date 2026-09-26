"""Plain-English explanations.

Templates, not a language model: every number in an explanation has to come from
the result object. The test that matters most asserts exactly that — a sentence
may never contain a figure the plan does not contain.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest
from supplyguard.narrative.explain import explain_allocation, explain_line, explain_scenario
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement


def _offers() -> pd.DataFrame:
    return pd.DataFrame([
        {"supplier_id": "a", "supplier_name": "Alpha Co", "material_id": "M1", "plant_id": "P1",
         "unit_price": 1.0, "capacity_per_week": 800, "moq": 0.0, "lead_days": 30.0,
         "p75_lead_days": 40.0, "delay_probability": 0.3, "quality_probability": 0.1,
         "origin": "real", "contract_max_share": 1.0},
        {"supplier_id": "b", "supplier_name": "Beta Co", "material_id": "M1", "plant_id": "P1",
         "unit_price": 1.2, "capacity_per_week": 800, "moq": 0.0, "lead_days": 30.0,
         "p75_lead_days": 40.0, "delay_probability": 0.05, "quality_probability": 0.1,
         "origin": "synthetic", "contract_max_share": 1.0},
    ])


@pytest.fixture
def plan():
    request = AllocationRequest(
        requirements=[Requirement("M1", "P1", 1, 1000.0)],
        max_supplier_share=0.6,
        min_suppliers_per_material=2,
    )
    return solve(request, _offers())


def test_explanation_reads_as_a_paragraph(plan) -> None:
    text = explain_allocation(plan)
    assert len(text) > 120
    assert text.endswith(".")


def test_every_number_in_the_text_comes_from_the_plan(plan) -> None:
    """The guard against invention: no figure may appear that the plan lacks."""
    text = explain_allocation(plan)
    quoted = {
        round(plan.material_cost),
        round(plan.total_cost),
        plan.suppliers_used,
        round(sum(line.qty for line in plan.lines)),
    }
    for number in re.findall(r"\d[\d,]*", text):
        value = int(number.replace(",", ""))
        if value > 100:                       # ignore small counts and percentages
            assert value in quoted, f"{value} appears in the text but not in the plan"


def test_a_generated_supplier_is_declared(plan) -> None:
    assert "generated suppliers" in explain_allocation(plan)


def test_comparison_numbers_are_woven_in(plan) -> None:
    comparison = {
        "historical_mix": {"total_cost_delta_pct": -19.4, "expected_late_delta_pct": -9.5},
        "cheapest_first": {"invoice_delta_pct": 1.8, "high_risk_delta_pp": -2.4},
    }
    text = explain_allocation(plan, comparison)
    assert "19.4% less" in text
    assert "1.8% dearer" in text


def test_an_infeasible_plan_says_so_plainly() -> None:
    request = AllocationRequest(requirements=[Requirement("UNKNOWN", "P1", 1, 10.0)])
    result = solve(request, _offers())
    text = explain_allocation(result)
    assert "No plan meets every constraint" in text


def test_line_explanations_name_the_supplier_and_the_share(plan) -> None:
    text = explain_line(plan.lines[0])
    assert plan.lines[0].supplier_name in text
    assert "%" in text


def test_scenario_text_distinguishes_absorbed_from_broken() -> None:
    absorbed = explain_scenario(
        "Supplier outage", {"total_cost_pct": 2.7, "expected_late_pct": -3.1, "suppliers_delta": 1},
        feasible=True,
    )
    assert "still meets demand" in absorbed

    broken = explain_scenario(
        "Lead-time shock", {"total_cost_pct": 0}, feasible=False, message="No plan satisfies it."
    )
    assert "cannot absorb" in broken
    assert "where the base needs widening" in broken
