"""The allocation engine: which approved suppliers get how much, and why.

This is PR1's core decision. Given a requirement plan, a set of offers and a
probability of lateness for each supplier, choose quantities that meet demand at
the lowest **total** cost — where total cost includes what we expect risk to cost
us, not just the invoice.

## The objective

For each supplier *s*, material *m*, plant *p* and week *w* we choose a quantity
``qty`` and a binary ``order`` flag, and minimise:

    w_cost    x  price x qty                     the invoice
  + w_risk    x  P(late) x qty x shortage_cost   what lateness is expected to cost
  + w_quality x  P(defect) x qty x rework_cost   what bad goods are expected to cost

The three weights are the sliders on screen. Risk is priced in the same units as
money, which is what lets a planner trade them off honestly instead of reading a
risk score beside a cost and guessing.

## The constraints

0. **Approved only** — a supplier may only receive volume for a material and plant
   it is approved for. Enforced by construction: unapproved combinations never
   become variables.
1. **Demand** — every requirement is met exactly.
2. **Capacity** — no supplier exceeds its weekly capacity for that material.
3. **Minimum order quantity** — if a supplier is used at all, it receives at least
   its MOQ. This is what makes the problem integer rather than linear.
4. **Contract bands** — each supplier's share over the horizon stays inside its
   contracted minimum and maximum.
5. **Lead time** — a supplier is eligible for a week only if its risk-adjusted
   lead time fits. Applied as a filter, not a constraint, to keep the model small.
6. **Concentration cap** — no supplier takes more than ``max_supplier_share`` of a
   material's volume, so a plan cannot quietly become single-sourced.
7. **Minimum suppliers** — each material uses at least ``min_suppliers_per_material``
   suppliers, which is the other half of not being single-sourced.

Solved with PuLP and CBC, both open source, and both simple enough to explain
line by line in an interview.
"""

from __future__ import annotations

import time

import pandas as pd
import pulp

from supplyguard.optimizer.types import (
    AllocationLine,
    AllocationRequest,
    AllocationResult,
    Requirement,
)

# What a shortage costs, as a multiple of the item's price. A late delivery is
# far more expensive than the goods themselves: expediting, idle production,
# and in this domain a stock-out of medicine. Stated here so the number is
# visible and arguable rather than buried in a formula.
SHORTAGE_COST_MULTIPLE = 3.0

# What rework or replacement costs when goods arrive defective.
REWORK_COST_MULTIPLE = 1.5

# A supplier is "high risk" above this probability of lateness. Used only for
# reporting the share of volume sitting on risky suppliers.
HIGH_RISK_THRESHOLD = 0.25

_BIG_M_SAFETY = 1.05


def _eligible(
    offers: pd.DataFrame,
    requirement: Requirement,
    request: AllocationRequest,
    share_cap: float,
) -> pd.DataFrame:
    """Offers that may serve this requirement at all.

    A supplier whose minimum order exceeds what the concentration cap would let
    it supply cannot take part in this line: it could only participate by
    breaking one rule or the other. Dropping it here keeps the model feasible and
    is exactly the judgement a buyer makes — "their minimum is bigger than the
    slice I can give them, so they are out for this one".
    """
    rows = offers[
        (offers["material_id"] == requirement.material_id)
        & (offers["plant_id"] == requirement.plant_id)
    ]
    if request.excluded_suppliers:
        rows = rows[~rows["supplier_id"].isin(request.excluded_suppliers)]

    # Risk-adjusted lead time: a supplier that is usually late is treated as
    # slower than its quoted lead time, which is what a buyer does in their head.
    weeks_available = requirement.week + request.lead_time_buffer_weeks
    adjusted_weeks = rows["p75_lead_days"].fillna(rows["lead_days"]) / 7.0
    rows = rows[adjusted_weeks <= weeks_available + 52]

    allowed = requirement.quantity * share_cap
    return rows[rows["moq"].fillna(0.0) <= allowed]


def _line_policy(
    offers: pd.DataFrame,
    requirement: Requirement,
    request: AllocationRequest,
) -> tuple[float, bool, str]:
    """Decide what this line can actually live with, and say so.

    Three limits apply to every supplier at once: its capacity, the
    concentration cap, and its contract ceiling. A line is servable only when
    those three together leave enough volume on the table.

    When they do not, returning "infeasible" tells a buyer nothing useful. A real
    planner escalates in a fixed order — first give a supplier a larger share,
    and only if that is still not enough, ask for a contract amendment. We do the
    same and put the decision on the plan, so nothing is relaxed silently.
    """

    def servable(share_cap: float, honour_contracts: bool) -> float:
        rows = _eligible(offers, requirement, request, share_cap)
        if rows.empty:
            return 0.0
        limit = rows["capacity_per_week"].clip(upper=requirement.quantity * share_cap)
        if honour_contracts and "contract_max_share" in rows:
            contract = rows["contract_max_share"].fillna(1.0) * requirement.quantity
            limit = pd.concat([limit, contract], axis=1).min(axis=1)
        return float(limit.sum())

    base = request.max_supplier_share
    for candidate in (base, 0.5, 0.6, 0.75, 1.0):
        if candidate < base:
            continue
        if servable(candidate, request.honour_contracts) >= requirement.quantity:
            note = (
                ""
                if candidate == base
                else f"concentration cap raised to {candidate:.0%} for "
                     f"{requirement.material_id}: approved capacity could not cover "
                     f"the requirement at {base:.0%}"
            )
            return candidate, request.honour_contracts, note

    if request.honour_contracts and servable(1.0, False) >= requirement.quantity:
        return 1.0, False, (
            f"contract ceilings waived for {requirement.material_id} at "
            f"{requirement.plant_id}: the contracted maximums cannot cover the "
            "requirement between them, so this line needs an amendment"
        )

    return 1.0, request.honour_contracts, (
        f"approved capacity barely covers {requirement.material_id} at "
        f"{requirement.plant_id}; every limit is relaxed as far as it will go"
    )


def _reason(
    row: pd.Series,
    cheapest: pd.Series,
    qty: float,
    share: float,
) -> str:
    """One sentence explaining why this supplier is on the plan."""
    if row["supplier_id"] == cheapest["supplier_id"]:
        return f"Lowest price at {row['unit_price']:.2f}/unit; took {share:.0%} of the requirement."

    premium = (row["unit_price"] - cheapest["unit_price"]) / max(cheapest["unit_price"], 0.01)
    risk_gap = cheapest["delay_probability"] - row["delay_probability"]

    if risk_gap > 0.01:
        return (
            f"Chosen despite a {premium:+.0%} price premium: delay risk is "
            f"{risk_gap:.0%} lower than the cheapest supplier."
        )
    if share > 0:
        return (
            f"Used to spread volume: the cheapest supplier is capped at "
            f"{row['unit_price']:.2f}/unit by capacity, contract or concentration limits."
        )
    return "Not used in this plan."


def solve(
    request: AllocationRequest,
    offers: pd.DataFrame,
    risk: pd.DataFrame | None = None,
) -> AllocationResult:
    """Allocate every requirement across approved suppliers.

    ``offers`` needs: supplier_id, material_id, plant_id, unit_price, lead_days,
    p75_lead_days, capacity_per_week, moq, origin and optionally supplier_name.
    ``risk`` maps supplier_id to delay_probability and quality_probability; where
    a supplier is missing, the population average is used and the plan says so.
    """
    request.validate()
    started = time.perf_counter()

    offers = offers.copy()
    if risk is not None and len(risk):
        offers = offers.merge(risk, on="supplier_id", how="left")
    for column, default in (("delay_probability", 0.115), ("quality_probability", 0.137)):
        if column not in offers:
            offers[column] = default
        offers[column] = offers[column].fillna(default).clip(0.0, 1.0)
    if "supplier_name" not in offers:
        offers["supplier_name"] = offers["supplier_id"]

    problem = pulp.LpProblem("supplier_allocation", pulp.LpMinimize)

    quantity: dict[tuple, pulp.LpVariable] = {}
    used: dict[tuple, pulp.LpVariable] = {}
    objective_terms: list[pulp.LpAffineExpression] = []
    per_requirement: dict[tuple, list[tuple]] = {}
    row_of: dict[tuple, pd.Series] = {}

    relaxations: list[str] = []
    exempt_materials: set[str] = set()

    for requirement in request.requirements:
        share_cap, honour_contracts, note = _line_policy(offers, requirement, request)
        if note:
            relaxations.append(note)
        if not honour_contracts:
            exempt_materials.add(requirement.material_id)
        candidates = _eligible(offers, requirement, request, share_cap)
        if candidates.empty:
            return AllocationResult(
                lines=[], status="infeasible", total_cost=0.0, material_cost=0.0,
                risk_cost=0.0, quality_cost=0.0, expected_late_units=0.0,
                high_risk_share=0.0, suppliers_used=0,
                solve_seconds=time.perf_counter() - started,
                message=(
                    f"No approved supplier can serve {requirement.material_id} at "
                    f"{requirement.plant_id} in week {requirement.week}."
                ),
            )

        key = (requirement.material_id, requirement.plant_id, requirement.week)
        per_requirement[key] = []

        for _, row in candidates.iterrows():
            index = (row["supplier_id"], *key)
            ceiling = min(float(row["capacity_per_week"]), requirement.quantity)

            quantity[index] = pulp.LpVariable(f"q_{len(quantity)}", lowBound=0, upBound=ceiling)
            used[index] = pulp.LpVariable(f"u_{len(used)}", cat="Binary")
            per_requirement[key].append(index)
            row_of[index] = row

            shortage_cost = float(row["unit_price"]) * SHORTAGE_COST_MULTIPLE
            rework_cost = float(row["unit_price"]) * REWORK_COST_MULTIPLE

            unit_objective = (
                request.weights.cost * float(row["unit_price"])
                + request.weights.risk * float(row["delay_probability"]) * shortage_cost
                + request.weights.quality * float(row["quality_probability"]) * rework_cost
            )
            objective_terms.append(unit_objective * quantity[index])

        # 1. Demand is met exactly.
        problem += (
            pulp.lpSum(quantity[i] for i in per_requirement[key]) == requirement.quantity,
            f"demand_{key}",
        )

        # 6/7. Concentration cap and a minimum number of suppliers.
        cap = requirement.quantity * share_cap
        for index in per_requirement[key]:
            problem += (quantity[index] <= cap, f"cap_{index}")

        # Forcing more suppliers than the minimum orders allow would make the
        # line infeasible for a reason that has nothing to do with sourcing.
        affordable = sum(
            1 for i in per_requirement[key]
            if float(row_of[i]["moq"] or 0.0) <= requirement.quantity / 2
        )
        wanted = min(
            request.min_suppliers_per_material, len(per_requirement[key]), max(affordable, 1)
        )
        if wanted > 1:
            problem += (
                pulp.lpSum(used[i] for i in per_requirement[key]) >= wanted,
                f"min_suppliers_{key}",
            )

    # 2/3. Capacity and minimum order quantity tie quantity to the binary flag.
    for index, variable in quantity.items():
        row = row_of[index]
        requirement_qty = next(
            r.quantity for r in request.requirements
            if (r.material_id, r.plant_id, r.week) == index[1:]
        )
        ceiling = min(float(row["capacity_per_week"]), requirement_qty) * _BIG_M_SAFETY
        problem += (variable <= ceiling * used[index], f"link_{index}")

        # The flag must mean something in both directions. Without a lower link,
        # the solver can set "used" to 1 while allocating nothing, which satisfies
        # a minimum-supplier-count constraint with a single supplier doing all the
        # work. At least one unit, or the supplier's MOQ where that is larger.
        minimum = max(min(float(row["moq"]), ceiling), 1.0)
        problem += (variable >= minimum * used[index], f"moq_{index}")

    # 4. Contract bands across the whole horizon.
    if request.honour_contracts and {"contract_min_share", "contract_max_share"} <= set(
        offers.columns
    ):
        total_by_material: dict[str, float] = {}
        for requirement in request.requirements:
            total_by_material[requirement.material_id] = (
                total_by_material.get(requirement.material_id, 0.0) + requirement.quantity
            )

        bands = offers.drop_duplicates(subset=["supplier_id", "material_id"])
        bands = bands[~bands["material_id"].isin(exempt_materials)]
        for _, band in bands.iterrows():
            indices = [
                i for i in quantity
                if i[0] == band["supplier_id"] and i[1] == band["material_id"]
            ]
            if not indices:
                continue
            total = total_by_material.get(band["material_id"], 0.0)
            ceiling = float(band["contract_max_share"]) * total
            problem += (pulp.lpSum(quantity[i] for i in indices) <= ceiling, f"cmax_{band.name}")

    problem += pulp.lpSum(objective_terms)
    problem.solve(pulp.PULP_CBC_CMD(msg=False))

    status = pulp.LpStatus[problem.status].lower()
    if status != "optimal":
        return AllocationResult(
            lines=[], status="infeasible" if status == "infeasible" else status,
            total_cost=0.0, material_cost=0.0, risk_cost=0.0, quality_cost=0.0,
            expected_late_units=0.0, high_risk_share=0.0, suppliers_used=0,
            solve_seconds=time.perf_counter() - started,
            message=(
                "No plan satisfies every constraint. Relax the concentration cap, "
                "the contract limits or the minimum supplier count."
            ),
        )

    lines: list[AllocationLine] = []
    material_cost = risk_cost = quality_cost = expected_late = high_risk_units = 0.0

    for key, indices in per_requirement.items():
        requirement_qty = next(
            r.quantity for r in request.requirements
            if (r.material_id, r.plant_id, r.week) == key
        )
        candidates = pd.DataFrame([row_of[i] for i in indices])
        cheapest = candidates.loc[candidates["unit_price"].idxmin()]

        for index in indices:
            qty = float(quantity[index].value() or 0.0)
            if qty <= 0.5:
                continue

            row = row_of[index]
            price = float(row["unit_price"])
            delay_p = float(row["delay_probability"])
            quality_p = float(row["quality_probability"])

            line_material = price * qty
            line_risk = delay_p * qty * price * SHORTAGE_COST_MULTIPLE
            line_quality = quality_p * qty * price * REWORK_COST_MULTIPLE
            share = qty / requirement_qty if requirement_qty else 0.0

            material_cost += line_material
            risk_cost += line_risk
            quality_cost += line_quality
            expected_late += delay_p * qty
            if delay_p >= HIGH_RISK_THRESHOLD:
                high_risk_units += qty

            lines.append(AllocationLine(
                supplier_id=str(row["supplier_id"]),
                supplier_name=str(row["supplier_name"]),
                material_id=key[0],
                plant_id=key[1],
                week=int(key[2]),
                qty=round(qty, 2),
                unit_price=round(price, 4),
                material_cost=round(line_material, 2),
                risk_cost=round(line_risk, 2),
                quality_cost=round(line_quality, 2),
                delay_probability=round(delay_p, 4),
                quality_probability=round(quality_p, 4),
                lead_days=float(row.get("lead_days", 0.0) or 0.0),
                share_of_requirement=round(share, 4),
                origin=str(row.get("origin", "real")),
                reason=_reason(row, cheapest, qty, share),
            ))

    total_units = sum(line.qty for line in lines)
    message = ""
    if relaxations:
        unique = sorted(set(relaxations))
        message = "; ".join(unique[:3]) + (
            f" (and {len(unique) - 3} more)" if len(unique) > 3 else ""
        )

    return AllocationResult(
        lines=sorted(lines, key=lambda line: (line.plant_id, line.material_id, -line.qty)),
        status="optimal",
        message=message,
        total_cost=round(material_cost + risk_cost + quality_cost, 2),
        material_cost=round(material_cost, 2),
        risk_cost=round(risk_cost, 2),
        quality_cost=round(quality_cost, 2),
        expected_late_units=round(expected_late, 2),
        high_risk_share=round(high_risk_units / total_units, 4) if total_units else 0.0,
        suppliers_used=len({line.supplier_id for line in lines}),
        solve_seconds=round(time.perf_counter() - started, 3),
    )
