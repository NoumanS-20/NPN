"""What the optimiser is actually worth, measured against how buying is done today.

A plan is only impressive next to an alternative. These are the three
alternatives a procurement team would recognise, and the comparison against them
is where our headline savings number comes from.

* **cheapest_first** — fill each requirement from the lowest price upward, stop
  when demand is met. This is what a spreadsheet does, and it is the hardest
  baseline to beat on invoice cost, because on invoice cost alone it is optimal.
  We do not beat it there and we do not pretend to: we beat it on *total* cost
  once late deliveries are priced in.
* **equal_split** — divide each requirement evenly across approved suppliers.
  The "play it safe, spread the risk" instinct, which spreads volume onto
  expensive and unreliable suppliers alike.
* **historical_mix** — buy in the same proportions the organisation used last
  year. The true status quo, and the most honest comparison of all, because it
  is what the money was actually spent on.

Every baseline respects capacity, because a comparison against an impossible
plan is worthless. None of them respects the concentration cap or contract
limits, because those are decisions the optimiser makes and the alternatives do
not.
"""

from __future__ import annotations

import time

import pandas as pd

from supplyguard.optimizer.model import (
    HIGH_RISK_THRESHOLD,
    REWORK_COST_MULTIPLE,
    SHORTAGE_COST_MULTIPLE,
)
from supplyguard.optimizer.types import (
    AllocationLine,
    AllocationRequest,
    AllocationResult,
    Requirement,
)


def _prepare(offers: pd.DataFrame, risk: pd.DataFrame | None) -> pd.DataFrame:
    prepared = offers.copy()
    if risk is not None and len(risk):
        prepared = prepared.merge(risk, on="supplier_id", how="left")
    for column, default in (("delay_probability", 0.115), ("quality_probability", 0.137)):
        if column not in prepared:
            prepared[column] = default
        prepared[column] = prepared[column].fillna(default).clip(0.0, 1.0)
    if "supplier_name" not in prepared:
        prepared["supplier_name"] = prepared["supplier_id"]
    return prepared


def _candidates(
    offers: pd.DataFrame, requirement: Requirement, excluded: tuple[str, ...]
) -> pd.DataFrame:
    rows = offers[
        (offers["material_id"] == requirement.material_id)
        & (offers["plant_id"] == requirement.plant_id)
    ]
    return rows[~rows["supplier_id"].isin(excluded)] if excluded else rows


def _assemble(lines: list[AllocationLine], name: str, seconds: float) -> AllocationResult:
    material = sum(line.material_cost for line in lines)
    risk_cost = sum(line.risk_cost for line in lines)
    quality = sum(line.quality_cost for line in lines)
    units = sum(line.qty for line in lines)
    late = sum(line.delay_probability * line.qty for line in lines)
    high_risk = sum(
        line.qty for line in lines if line.delay_probability >= HIGH_RISK_THRESHOLD
    )

    return AllocationResult(
        lines=lines,
        status="optimal" if lines else "infeasible",
        total_cost=round(material + risk_cost + quality, 2),
        material_cost=round(material, 2),
        risk_cost=round(risk_cost, 2),
        quality_cost=round(quality, 2),
        expected_late_units=round(late, 2),
        high_risk_share=round(high_risk / units, 4) if units else 0.0,
        suppliers_used=len({line.supplier_id for line in lines}),
        solve_seconds=round(seconds, 3),
        message=f"baseline: {name}",
    )


def _line(row: pd.Series, requirement: Requirement, qty: float, reason: str) -> AllocationLine:
    price = float(row["unit_price"])
    delay_p = float(row["delay_probability"])
    quality_p = float(row["quality_probability"])
    return AllocationLine(
        supplier_id=str(row["supplier_id"]),
        supplier_name=str(row["supplier_name"]),
        material_id=requirement.material_id,
        plant_id=requirement.plant_id,
        week=requirement.week,
        qty=round(qty, 2),
        unit_price=round(price, 4),
        material_cost=round(price * qty, 2),
        risk_cost=round(delay_p * qty * price * SHORTAGE_COST_MULTIPLE, 2),
        quality_cost=round(quality_p * qty * price * REWORK_COST_MULTIPLE, 2),
        delay_probability=round(delay_p, 4),
        quality_probability=round(quality_p, 4),
        lead_days=float(row.get("lead_days", 0.0) or 0.0),
        share_of_requirement=round(qty / requirement.quantity, 4) if requirement.quantity else 0.0,
        origin=str(row.get("origin", "real")),
        reason=reason,
    )


def cheapest_first(
    request: AllocationRequest, offers: pd.DataFrame, risk: pd.DataFrame | None = None
) -> AllocationResult:
    """Buy from the lowest price upward until demand is met."""
    started = time.perf_counter()
    prepared = _prepare(offers, risk)
    lines: list[AllocationLine] = []

    for requirement in request.requirements:
        candidates = _candidates(prepared, requirement, request.excluded_suppliers)
        remaining = requirement.quantity
        for _, row in candidates.sort_values("unit_price").iterrows():
            if remaining <= 0:
                break
            qty = min(remaining, float(row["capacity_per_week"]))
            if qty <= 0:
                continue
            lines.append(_line(row, requirement, qty, "Cheapest available supplier with capacity."))
            remaining -= qty

    return _assemble(lines, "cheapest first", time.perf_counter() - started)


def equal_split(
    request: AllocationRequest, offers: pd.DataFrame, risk: pd.DataFrame | None = None
) -> AllocationResult:
    """Divide each requirement evenly across everyone approved to supply it."""
    started = time.perf_counter()
    prepared = _prepare(offers, risk)
    lines: list[AllocationLine] = []

    for requirement in request.requirements:
        candidates = _candidates(prepared, requirement, request.excluded_suppliers)
        if candidates.empty:
            continue

        share = requirement.quantity / len(candidates)
        allocated = 0.0
        for _, row in candidates.iterrows():
            qty = min(share, float(row["capacity_per_week"]))
            if qty > 0:
                lines.append(_line(row, requirement, qty, "Equal share across approved suppliers."))
                allocated += qty

        # Capacity can leave a shortfall; push it onto whoever has room, so the
        # baseline meets demand and the comparison stays fair.
        shortfall = requirement.quantity - allocated
        if shortfall > 0.5:
            for _, row in candidates.sort_values("capacity_per_week", ascending=False).iterrows():
                headroom = float(row["capacity_per_week"]) - share
                take = min(shortfall, max(headroom, 0.0))
                if take > 0:
                    reason = "Covering the equal-split shortfall."
                    lines.append(_line(row, requirement, take, reason))
                    shortfall -= take
                if shortfall <= 0.5:
                    break

    return _assemble(lines, "equal split", time.perf_counter() - started)


def historical_mix(
    request: AllocationRequest,
    offers: pd.DataFrame,
    history: pd.DataFrame,
    risk: pd.DataFrame | None = None,
) -> AllocationResult:
    """Buy in the proportions the organisation actually used last year."""
    started = time.perf_counter()
    prepared = _prepare(offers, risk)

    shares = (
        history.groupby(["item", "supplier_id"])["qty"].sum().rename("volume").reset_index()
        .rename(columns={"item": "material_id"})
    )
    totals = shares.groupby("material_id")["volume"].transform("sum")
    shares["share"] = shares["volume"] / totals

    lines: list[AllocationLine] = []
    for requirement in request.requirements:
        candidates = _candidates(prepared, requirement, request.excluded_suppliers)
        if candidates.empty:
            continue

        weights = candidates.merge(
            shares[shares["material_id"] == requirement.material_id][["supplier_id", "share"]],
            on="supplier_id",
            how="left",
        )
        weights["share"] = weights["share"].fillna(0.0)
        if weights["share"].sum() <= 0:
            weights["share"] = 1.0 / len(weights)
        else:
            weights["share"] = weights["share"] / weights["share"].sum()

        allocated = 0.0
        for _, row in weights.iterrows():
            qty = min(requirement.quantity * float(row["share"]), float(row["capacity_per_week"]))
            if qty > 0:
                lines.append(_line(row, requirement, qty, "Same proportions as last year."))
                allocated += qty

        shortfall = requirement.quantity - allocated
        if shortfall > 0.5:
            for _, row in weights.sort_values("capacity_per_week", ascending=False).iterrows():
                take = min(shortfall, float(row["capacity_per_week"]))
                if take > 0:
                    reason = "Covering the historical shortfall."
                    lines.append(_line(row, requirement, take, reason))
                    shortfall -= take
                if shortfall <= 0.5:
                    break

    return _assemble(lines, "historical mix", time.perf_counter() - started)


def compare(optimised: AllocationResult, baselines: dict[str, AllocationResult]) -> dict[str, dict]:
    """How the plan differs from each alternative, in the terms a buyer cares about."""
    comparison: dict[str, dict] = {}
    for name, baseline in baselines.items():
        if not baseline.lines:
            comparison[name] = {"status": baseline.status}
            continue

        comparison[name] = {
            "status": baseline.status,
            "baseline_invoice": baseline.material_cost,
            "baseline_total_cost": baseline.total_cost,
            "baseline_expected_late_units": baseline.expected_late_units,
            "baseline_high_risk_share": baseline.high_risk_share,
            "invoice_delta_pct": round(
                (optimised.material_cost - baseline.material_cost)
                / baseline.material_cost * 100, 2,
            ) if baseline.material_cost else 0.0,
            "total_cost_delta_pct": round(
                (optimised.total_cost - baseline.total_cost) / baseline.total_cost * 100, 2,
            ) if baseline.total_cost else 0.0,
            "expected_late_delta_pct": round(
                (optimised.expected_late_units - baseline.expected_late_units)
                / baseline.expected_late_units * 100, 2,
            ) if baseline.expected_late_units else 0.0,
            "high_risk_delta_pp": round(
                (optimised.high_risk_share - baseline.high_risk_share) * 100, 2
            ),
            "suppliers_delta": optimised.suppliers_used - baseline.suppliers_used,
        }
    return comparison


def run_all(
    request: AllocationRequest,
    offers: pd.DataFrame,
    history: pd.DataFrame,
    risk: pd.DataFrame | None = None,
) -> dict[str, AllocationResult]:
    """Every baseline, ready to compare against a plan."""
    return {
        "cheapest_first": cheapest_first(request, offers, risk),
        "equal_split": equal_split(request, offers, risk),
        "historical_mix": historical_mix(request, offers, history, risk),
    }
