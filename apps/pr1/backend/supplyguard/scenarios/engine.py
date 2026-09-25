"""What-if scenarios: re-plan under a disruption and show what it costs.

The use case asks for "scenario analysis for supplier disruptions or demand
spikes", and this is the part of the demo a panel will want to drive themselves.

Each scenario is a **pure transformation of the inputs** followed by a fresh
solve. Nothing about the optimiser changes, which matters for two reasons: the
before and after are genuinely comparable, and there is no separate "scenario
mode" that could behave differently from the real planner.

The four scenarios are the ones a procurement team actually rehearses:

* **supplier_outage** — a supplier goes down. Plant fire, regulatory suspension,
  insolvency. The question is whether the rest of the base can absorb it.
* **demand_spike** — requirements jump. An epidemic, a funding release, a
  competitor's recall.
* **lead_time_shock** — everything takes longer. Port congestion, customs.
* **price_shock** — input costs jump for a group of suppliers.

Every scenario reports the same four numbers, because those are the four a buyer
is judged on: what it costs, how late it is likely to be, how concentrated the
risk is, and whether the plan is possible at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, AllocationResult, Requirement


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    description: str
    parameter: str
    parameter_label: str
    default: float
    apply: Callable[[dict, dict], dict]


@dataclass(frozen=True)
class ScenarioResult:
    key: str
    name: str
    parameters: dict[str, Any]
    before: AllocationResult
    after: AllocationResult
    deltas: dict[str, float]
    narrative: str


def _outage(inputs: dict, parameters: dict) -> dict:
    """Remove a supplier from every requirement it serves."""
    supplier_id = parameters.get("supplier_id")
    if not supplier_id:
        raise ValueError("supplier_outage needs a supplier_id")

    request: AllocationRequest = inputs["request"]
    excluded = (*request.excluded_suppliers, str(supplier_id))
    return {**inputs, "request": replace(request, excluded_suppliers=excluded)}


def _demand_spike(inputs: dict, parameters: dict) -> dict:
    """Raise every requirement by a percentage."""
    uplift = float(parameters.get("uplift_pct", 30.0)) / 100.0
    request: AllocationRequest = inputs["request"]
    scaled = [
        Requirement(r.material_id, r.plant_id, r.week, round(r.quantity * (1 + uplift), 2))
        for r in request.requirements
    ]
    return {**inputs, "request": replace(request, requirements=scaled)}


def _lead_time_shock(inputs: dict, parameters: dict) -> dict:
    """Add weeks to every supplier's lead time.

    Longer lead times make suppliers ineligible for near weeks, which is exactly
    what happens when a port backs up: the goods are available, they just cannot
    arrive in time.
    """
    extra_weeks = float(parameters.get("extra_weeks", 2.0))
    offers: pd.DataFrame = inputs["offers"].copy()
    offers["lead_days"] = offers["lead_days"] + extra_weeks * 7
    offers["p75_lead_days"] = offers["p75_lead_days"].fillna(offers["lead_days"]) + extra_weeks * 7
    return {**inputs, "offers": offers}


def _price_shock(inputs: dict, parameters: dict) -> dict:
    """Raise prices, either everywhere or for one country's suppliers."""
    increase = float(parameters.get("increase_pct", 25.0)) / 100.0
    country = parameters.get("country")

    offers: pd.DataFrame = inputs["offers"].copy()
    if country and "country" in offers:
        affected = offers["country"] == country
    else:
        affected = pd.Series(True, index=offers.index)
    offers.loc[affected, "unit_price"] = offers.loc[affected, "unit_price"] * (1 + increase)
    return {**inputs, "offers": offers}


SCENARIOS: dict[str, Scenario] = {
    "supplier_outage": Scenario(
        key="supplier_outage",
        name="Supplier outage",
        description="A supplier stops delivering. Can the approved base absorb it?",
        parameter="supplier_id",
        parameter_label="Supplier",
        default=0.0,
        apply=_outage,
    ),
    "demand_spike": Scenario(
        key="demand_spike",
        name="Demand spike",
        description="Requirements jump across the board.",
        parameter="uplift_pct",
        parameter_label="Uplift (%)",
        default=30.0,
        apply=_demand_spike,
    ),
    "lead_time_shock": Scenario(
        key="lead_time_shock",
        name="Lead-time shock",
        description="Everything takes longer to arrive.",
        parameter="extra_weeks",
        parameter_label="Extra weeks",
        default=2.0,
        apply=_lead_time_shock,
    ),
    "price_shock": Scenario(
        key="price_shock",
        name="Price shock",
        description="Input costs rise for suppliers in one country, or everywhere.",
        parameter="increase_pct",
        parameter_label="Increase (%)",
        default=25.0,
        apply=_price_shock,
    ),
}


def _deltas(before: AllocationResult, after: AllocationResult) -> dict[str, float]:
    def pct(new: float, old: float) -> float:
        return round((new - old) / old * 100, 2) if old else 0.0

    return {
        "total_cost_pct": pct(after.total_cost, before.total_cost),
        "invoice_pct": pct(after.material_cost, before.material_cost),
        "expected_late_pct": pct(after.expected_late_units, before.expected_late_units),
        "high_risk_pp": round((after.high_risk_share - before.high_risk_share) * 100, 2),
        "suppliers_delta": after.suppliers_used - before.suppliers_used,
        "unmet_lines": len(before.lines) - len(after.lines) if not after.is_optimal else 0,
    }


def _narrative(scenario: Scenario, deltas: dict[str, float], after: AllocationResult) -> str:
    """One sentence a planner could paste into an email."""
    if not after.is_optimal:
        return (
            f"{scenario.name} leaves the plan unservable: {after.message} "
            "The approved supplier base cannot absorb this disruption."
        )

    parts = [f"{scenario.name}: total cost {deltas['total_cost_pct']:+.1f}%"]
    if deltas["expected_late_pct"]:
        parts.append(f"expected late units {deltas['expected_late_pct']:+.1f}%")
    if deltas["suppliers_delta"]:
        parts.append(f"{abs(deltas['suppliers_delta'])} "
                     f"{'more' if deltas['suppliers_delta'] > 0 else 'fewer'} suppliers used")
    if deltas["high_risk_pp"]:
        parts.append(f"high-risk volume {deltas['high_risk_pp']:+.1f} points")
    return ", ".join(parts) + "."


def run(
    key: str,
    parameters: dict[str, Any],
    request: AllocationRequest,
    offers: pd.DataFrame,
    risk: pd.DataFrame | None = None,
    before: AllocationResult | None = None,
) -> ScenarioResult:
    """Solve the plan, apply the disruption, solve again, and report the difference."""
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario {key!r}; choose from {sorted(SCENARIOS)}")

    scenario = SCENARIOS[key]
    baseline = before if before is not None else solve(request, offers, risk)

    inputs = scenario.apply({"request": request, "offers": offers, "risk": risk}, parameters)
    after = solve(inputs["request"], inputs["offers"], inputs.get("risk"))

    deltas = _deltas(baseline, after)
    return ScenarioResult(
        key=key,
        name=scenario.name,
        parameters=dict(parameters),
        before=baseline,
        after=after,
        deltas=deltas,
        narrative=_narrative(scenario, deltas, after),
    )


def largest_supplier(result: AllocationResult) -> str | None:
    """The supplier carrying the most volume — the obvious one to knock out."""
    totals = result.by_supplier()
    return max(totals, key=totals.get) if totals else None
