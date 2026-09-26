"""Two scenarios, preloaded, so the demo starts from a known place.

One clean baseline and one disruption per application. The panel can change an
input from either — the weights, the cap, which supplier goes down — and the
plan re-solves in under a second, because nothing here trains anything.

Having these written down rather than typed live is deliberate. A demo where
someone fills in four fields from memory is a demo with four chances to fumble.
"""

from __future__ import annotations

from dataclasses import dataclass

from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights


@dataclass(frozen=True)
class DemoScenario:
    key: str
    name: str
    description: str
    say_this: str
    plant_id: str | None
    weeks: int
    weights: tuple[float, float, float]
    max_supplier_share: float
    scenario: str | None = None
    scenario_parameters: dict | None = None


PRELOADED: dict[str, DemoScenario] = {
    "baseline": DemoScenario(
        key="baseline",
        name="The monthly buy",
        description="Nigeria, two weeks, balanced weights. The plan as a buyer would run it.",
        say_this=(
            "This is one month's buy for our largest plant. Every supplier on it is approved for "
            "that material, and the split you see balances price against the risk each supplier "
            "delivers late. Watch what happens when I stop caring about risk."
        ),
        plant_id="plant-nigeria",
        weeks=2,
        weights=(1.0, 1.0, 1.0),
        max_supplier_share=0.4,
    ),
    "price_only": DemoScenario(
        key="price_only",
        name="Buying on price alone",
        description="The same requirement with the risk weight at zero — the spreadsheet answer.",
        say_this=(
            "Same demand, same suppliers, risk weight at zero. The invoice drops slightly and the "
            "volume sitting on high-risk suppliers roughly doubles. That difference is the whole "
            "argument for pricing risk in money."
        ),
        plant_id="plant-nigeria",
        weeks=2,
        weights=(1.0, 0.0, 0.0),
        max_supplier_share=0.4,
    ),
    "disruption": DemoScenario(
        key="disruption",
        name="The biggest supplier goes down",
        description="An outage of whichever supplier is carrying the most volume.",
        say_this=(
            "Now the supplier carrying the most volume stops delivering. The plan re-solves in "
            "about two seconds, still meets demand in full, and costs a few per cent more. That "
            "is what a broad approved base buys you."
        ),
        plant_id="plant-nigeria",
        weeks=2,
        weights=(1.0, 1.0, 1.0),
        max_supplier_share=0.4,
        scenario="supplier_outage",
        scenario_parameters={},
    ),
}


def to_request(scenario: DemoScenario, requirements: list[Requirement]) -> AllocationRequest:
    """Turn a demo scenario into an allocation request."""
    cost, risk, quality = scenario.weights
    return AllocationRequest(
        requirements=requirements,
        weights=Weights(cost=cost, risk=risk, quality=quality),
        max_supplier_share=scenario.max_supplier_share,
    )


def as_api_body(scenario: DemoScenario) -> dict:
    """The JSON a screen would post — the same call the demo makes."""
    cost, risk, quality = scenario.weights
    return {
        "plant_id": scenario.plant_id,
        "weeks": scenario.weeks,
        "max_supplier_share": scenario.max_supplier_share,
        "weights": {"cost": cost, "risk": risk, "quality": quality},
    }
