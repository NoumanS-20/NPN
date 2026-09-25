"""Request and response shapes for the SupplyGuard API.

These mirror the optimiser's dataclasses rather than wrapping them in something
cleverer, so the JSON a screen receives reads the same as the objects the model
produces.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from supplyguard.config import MAX_SUPPLIER_SHARE, MIN_SUPPLIERS_PER_MATERIAL


class WeightsIn(BaseModel):
    cost: float = Field(1.0, ge=0, le=10, description="Weight on the invoice price")
    risk: float = Field(1.0, ge=0, le=10, description="Weight on expected lateness cost")
    quality: float = Field(1.0, ge=0, le=10, description="Weight on expected rework cost")


class RequirementIn(BaseModel):
    material_id: str
    plant_id: str
    week: int = Field(ge=1, le=52)
    quantity: float = Field(gt=0)


class AllocateIn(BaseModel):
    """Either send explicit requirements, or let the server use the plan."""

    requirements: list[RequirementIn] | None = None
    weights: WeightsIn = Field(default_factory=WeightsIn)
    max_supplier_share: float = Field(MAX_SUPPLIER_SHARE, gt=0, le=1)
    min_suppliers_per_material: int = Field(MIN_SUPPLIERS_PER_MATERIAL, ge=1, le=10)
    honour_contracts: bool = True
    excluded_suppliers: list[str] = Field(default_factory=list)
    plant_id: str | None = Field(None, description="Limit the plan to one plant")
    material_id: str | None = Field(None, description="Limit the plan to one material")
    weeks: int | None = Field(None, ge=1, le=52, description="Limit the horizon")


class AllocationLineOut(BaseModel):
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


class AllocationOut(BaseModel):
    status: str
    total_cost: float
    material_cost: float
    risk_cost: float
    quality_cost: float
    expected_late_units: float
    high_risk_share: float
    suppliers_used: int
    solve_seconds: float
    message: str
    lines: list[AllocationLineOut]


class ComparisonOut(BaseModel):
    plan: AllocationOut
    baselines: dict[str, AllocationOut]
    comparison: dict[str, dict]


class ScoreOrderIn(BaseModel):
    """A draft purchase order, scored before it is released."""

    supplier_id: str
    material_id: str
    quantity: float = Field(gt=0)
    plant_id: str | None = None
    shipment_mode: str = "Air"


class RiskFactorOut(BaseModel):
    factor: str
    value: float | None
    contribution: float
    explanation: str


class ScoreOrderOut(BaseModel):
    supplier_id: str
    supplier_name: str
    delay_probability: float
    quality_probability: float
    has_measured_risk: bool
    verdict: str
    explanation: str
    top_factors: list[RiskFactorOut]


class ScenarioIn(BaseModel):
    parameters: dict[str, float | str] = Field(default_factory=dict)
    allocation: AllocateIn = Field(default_factory=AllocateIn)


class ScenarioOut(BaseModel):
    key: str
    name: str
    parameters: dict
    narrative: str
    deltas: dict[str, float]
    before: AllocationOut
    after: AllocationOut
