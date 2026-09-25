"""The contract between the allocation engine and everything that calls it.

Plain dataclasses, no solver types, so the API layer, the tests and the scenario
engine all speak the same language and none of them needs to know PuLP exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from supplyguard.config import MAX_SUPPLIER_SHARE, MIN_SUPPLIERS_PER_MATERIAL


@dataclass(frozen=True)
class Weights:
    """How the planner values cost against risk and quality.

    These are the sliders on screen. They are multipliers on money terms, so a
    risk weight of 1.0 means "price an expected shortage at its full cost", and
    2.0 means "I care about reliability twice as much as the money says I should".
    """

    cost: float = 1.0
    risk: float = 1.0
    quality: float = 1.0

    def validate(self) -> None:
        for name, value in (("cost", self.cost), ("risk", self.risk), ("quality", self.quality)):
            if value < 0:
                raise ValueError(f"weight {name} must not be negative, got {value}")


@dataclass(frozen=True)
class Requirement:
    """One line of demand: this material, at this plant, in this week."""

    material_id: str
    plant_id: str
    week: int
    quantity: float


@dataclass(frozen=True)
class AllocationRequest:
    requirements: list[Requirement]
    weights: Weights = field(default_factory=Weights)
    max_supplier_share: float = MAX_SUPPLIER_SHARE
    min_suppliers_per_material: int = MIN_SUPPLIERS_PER_MATERIAL
    honour_contracts: bool = True
    excluded_suppliers: tuple[str, ...] = ()
    lead_time_buffer_weeks: int = 0

    def validate(self) -> None:
        self.weights.validate()
        if not self.requirements:
            raise ValueError("an allocation request needs at least one requirement")
        if not 0 < self.max_supplier_share <= 1:
            raise ValueError("max_supplier_share must sit between 0 and 1")


@dataclass(frozen=True)
class AllocationLine:
    """One purchase decision, with the numbers behind it."""

    supplier_id: str
    supplier_name: str
    material_id: str
    plant_id: str
    week: int
    qty: float
    unit_price: float
    material_cost: float
    risk_cost: float
    quality_cost: float
    delay_probability: float
    quality_probability: float
    lead_days: float
    share_of_requirement: float
    origin: str
    reason: str


@dataclass(frozen=True)
class AllocationResult:
    lines: list[AllocationLine]
    status: str
    total_cost: float
    material_cost: float
    risk_cost: float
    quality_cost: float
    expected_late_units: float
    high_risk_share: float
    suppliers_used: int
    solve_seconds: float
    message: str = ""

    @property
    def is_optimal(self) -> bool:
        return self.status == "optimal"

    def by_supplier(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for line in self.lines:
            totals[line.supplier_id] = totals.get(line.supplier_id, 0.0) + line.qty
        return totals
