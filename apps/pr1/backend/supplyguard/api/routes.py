"""HTTP endpoints for SupplyGuard.

Everything the screens need, and everything a production system would attach to.
The API is deliberately the only way into the engine: the same calls that render
the dashboard would let an ERP post a requirement and read back an allocation,
which is the integration story in `docs/architecture.md`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from supplyguard.api.schemas import (
    AllocateIn,
    AllocationOut,
    ComparisonOut,
    ScenarioIn,
    ScenarioOut,
    ScoreOrderIn,
    ScoreOrderOut,
)
from supplyguard.api.state import state
from supplyguard.optimizer.baselines import compare, run_all
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights
from supplyguard.risk.explain import explain_order_risk
from supplyguard.scenarios.engine import SCENARIOS, largest_supplier
from supplyguard.scenarios.engine import run as run_scenario

router = APIRouter(prefix="/api")


def _to_out(result) -> dict[str, Any]:
    payload = asdict(result)
    payload["lines"] = [asdict(line) if not isinstance(line, dict) else line
                        for line in result.lines]
    return payload


def _requirements_from(body: AllocateIn) -> list[Requirement]:
    """Either the caller's own requirements, or the stored plan, filtered."""
    if body.requirements:
        return [
            Requirement(r.material_id, r.plant_id, r.week, r.quantity)
            for r in body.requirements
        ]

    plan = state.context.requirements
    if body.plant_id:
        plan = plan[plan["plant_id"] == body.plant_id]
    if body.material_id:
        plan = plan[plan["material_id"] == body.material_id]
    if body.weeks:
        plan = plan[plan["week"] <= body.weeks]

    if plan.empty:
        raise HTTPException(404, "No requirement lines match that filter.")

    return [
        Requirement(row.material_id, row.plant_id, int(row.week), float(row.required_qty))
        for row in plan.itertuples()
    ]


def _request_from(body: AllocateIn) -> AllocationRequest:
    return AllocationRequest(
        requirements=_requirements_from(body),
        weights=Weights(body.weights.cost, body.weights.risk, body.weights.quality),
        max_supplier_share=body.max_supplier_share,
        min_suppliers_per_material=body.min_suppliers_per_material,
        honour_contracts=body.honour_contracts,
        excluded_suppliers=tuple(body.excluded_suppliers),
    )


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "app": "SupplyGuard", "loaded": state.is_loaded}


@router.get("/summary")
def summary() -> dict[str, Any]:
    return state.context.summary()


@router.get("/suppliers")
def suppliers(
    search: str | None = None,
    material_id: str | None = None,
    plant_id: str | None = None,
    origin: str | None = Query(None, pattern="^(real|synthetic|public-synthetic)$"),
    sort: str = "on_time_rate",
    descending: bool = True,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The comparison table: every supplier, with performance and risk."""
    rows = state.suppliers_view()

    if material_id or plant_id:
        approved = state.context.asl
        if material_id:
            approved = approved[approved["material_id"] == material_id]
        if plant_id:
            approved = approved[approved["plant_id"] == plant_id]
        rows = rows[rows["supplier_id"].isin(approved["supplier_id"])]

    if origin:
        rows = rows[rows["origin"] == origin]
    if search:
        needle = search.lower()
        rows = rows[rows["name"].str.lower().str.contains(needle, na=False)]

    if sort in rows.columns:
        rows = rows.sort_values(sort, ascending=not descending, na_position="last")

    total = len(rows)
    page = rows.iloc[offset : offset + limit]
    return {
        "total": int(total),
        "offset": offset,
        "limit": limit,
        "rows": page.replace({pd.NA: None}).where(pd.notna(page), None).to_dict("records"),
    }


@router.get("/materials")
def materials() -> list[dict[str, Any]]:
    plan = state.context.requirements
    grouped = plan.groupby("material_id").agg(
        plants=("plant_id", "nunique"),
        weeks=("week", "nunique"),
        total_units=("required_qty", "sum"),
    ).reset_index()
    approvals = state.context.asl.groupby("material_id")["supplier_id"].nunique()
    grouped["approved_suppliers"] = grouped["material_id"].map(approvals).fillna(0).astype(int)
    return grouped.to_dict("records")


@router.get("/plants")
def plants() -> list[dict[str, Any]]:
    return state.context.plants.to_dict("records")


@router.get("/requirements")
def requirements(
    plant_id: str | None = None, material_id: str | None = None
) -> list[dict[str, Any]]:
    plan = state.context.requirements
    if plant_id:
        plan = plan[plan["plant_id"] == plant_id]
    if material_id:
        plan = plan[plan["material_id"] == material_id]
    return plan.to_dict("records")


@router.post("/allocate", response_model=AllocationOut)
def allocate(body: AllocateIn) -> dict[str, Any]:
    """The core call: plan the buy."""
    result = solve(_request_from(body), state.context.offers, state.context.risk)
    return _to_out(result)


@router.post("/allocate/compare", response_model=ComparisonOut)
def allocate_compare(body: AllocateIn) -> dict[str, Any]:
    """The plan, the three alternatives, and the difference between them."""
    request = _request_from(body)
    plan = solve(request, state.context.offers, state.context.risk)
    baselines = run_all(request, state.context.offers, state.context.orders, state.context.risk)
    return {
        "plan": _to_out(plan),
        "baselines": {name: _to_out(result) for name, result in baselines.items()},
        "comparison": compare(plan, baselines),
    }


@router.post("/risk/score-po", response_model=ScoreOrderOut)
def score_po(body: ScoreOrderIn) -> dict[str, Any]:
    """Score a draft purchase order before it is released."""
    supplier = state.context.suppliers[
        state.context.suppliers["supplier_id"] == body.supplier_id
    ]
    if supplier.empty:
        raise HTTPException(404, f"Unknown supplier {body.supplier_id!r}.")

    return explain_order_risk(
        supplier=supplier.iloc[0],
        risk=state.risk_for(body.supplier_id),
        offers=state.context.offers,
        material_id=body.material_id,
        quantity=body.quantity,
        plant_id=body.plant_id,
    )


@router.get("/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return [
        {
            "key": s.key, "name": s.name, "description": s.description,
            "parameter": s.parameter, "parameter_label": s.parameter_label,
            "default": s.default,
        }
        for s in SCENARIOS.values()
    ]


@router.post("/scenarios/{key}", response_model=ScenarioOut)
def run_scenario_endpoint(key: str, body: ScenarioIn) -> dict[str, Any]:
    if key not in SCENARIOS:
        raise HTTPException(404, f"Unknown scenario {key!r}.")

    request = _request_from(body.allocation)
    before = solve(request, state.context.offers, state.context.risk)

    parameters = dict(body.parameters)
    if key == "supplier_outage" and not parameters.get("supplier_id"):
        target = largest_supplier(before)
        if not target:
            raise HTTPException(400, "No plan to disrupt.")
        parameters["supplier_id"] = target

    try:
        result = run_scenario(
            key, parameters, request, state.context.offers, state.context.risk, before=before
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    return {
        "key": result.key, "name": result.name, "parameters": result.parameters,
        "narrative": result.narrative, "deltas": result.deltas,
        "before": _to_out(result.before), "after": _to_out(result.after),
    }


@router.get("/models/metrics")
def model_metrics() -> dict[str, Any]:
    """Every model's measured performance, including the two that did not ship."""
    return state.context.metrics


@router.get("/kpis")
def kpis() -> dict[str, Any]:
    """The headline numbers, computed on the stored plan."""
    return state.kpis()
