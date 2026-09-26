"""Explain a risk score in terms a buyer can act on.

A probability alone is not actionable. "68% likely to be late, mostly because
this supplier has been late on 4 of their last 9 orders and the order is three
times their usual size" tells a buyer what to do about it.

The factors are read from the supplier's own record rather than from the model's
internals, deliberately. A buyer can check every one of them against their own
knowledge, which is what makes the score trustworthy — and it keeps the
explanation honest when the score comes from the observed-rate fallback rather
than a model.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Above this, an order is worth a second look before release.
_REVIEW_THRESHOLD = 0.25
_HIGH_THRESHOLD = 0.40

# An order beyond what a supplier can physically make in the quoted lead time is
# a problem the delay model cannot see: the model scores the supplier, not the
# size of what we are asking for. So capacity is checked separately, in
# arithmetic, and it can overrule a comfortable probability.
_STRAIN_REVIEW = 1.0
_STRAIN_HIGH = 2.0


def _format_multiple(ratio: float) -> str:
    """Read a ratio the way a buyer would say it out loud."""
    if ratio >= 2:
        return f"{ratio:,.0f}x" if ratio >= 10 else f"{ratio:.1f}x"
    return f"{ratio:.0%}"


def _verdict(probability: float, strain: float | None = None) -> tuple[str, str]:
    """Combine the model's view of the supplier with what they can actually make.

    Two different questions, deliberately kept apart: "do they deliver late?" is
    a prediction, "can they make this much in time?" is arithmetic. The worse of
    the two decides, and the advice says which one spoke.
    """
    if strain is not None and strain >= _STRAIN_HIGH:
        return "high", (
            "Hold. This is more than the supplier can make in the quoted lead time, whatever "
            "their delivery record says — split it across suppliers or move the date."
        )
    if probability >= _HIGH_THRESHOLD:
        return "high", (
            "Hold for review. Consider splitting this order or bringing the date forward."
        )
    if strain is not None and strain >= _STRAIN_REVIEW:
        return "elevated", (
            "Releasable only if they can add capacity: this order uses all of their output "
            "for the whole lead time, leaving no room for anything to go wrong."
        )
    if probability >= _REVIEW_THRESHOLD:
        return "elevated", "Releasable, but worth a buffer on the need-by date."
    return "normal", "Safe to release on the planned date."


def explain_order_risk(
    supplier: pd.Series,
    risk: pd.Series | None,
    offers: pd.DataFrame,
    material_id: str,
    quantity: float,
    plant_id: str | None = None,
) -> dict[str, Any]:
    """Score a draft order and say what drives the score."""
    delay_p = float(risk["delay_probability"]) if risk is not None else 0.115
    quality_p = float(risk["quality_probability"]) if risk is not None else 0.137
    measured = bool(risk["has_measured_risk"]) if risk is not None else False

    factors: list[dict[str, Any]] = []

    on_time = supplier.get("on_time_rate")
    if pd.notna(on_time):
        late_rate = 1 - float(on_time)
        factors.append({
            "factor": "Delivery history",
            "value": round(late_rate, 4),
            "contribution": round(late_rate, 4),
            "explanation": (
                f"{late_rate:.0%} of this supplier's {int(supplier.get('orders', 0))} recorded "
                f"orders arrived late."
            ),
        })

    rows = offers[
        (offers["supplier_id"] == supplier["supplier_id"])
        & (offers["material_id"] == material_id)
    ]
    if plant_id:
        rows = rows[rows["plant_id"] == plant_id]

    if len(rows):
        offer = rows.iloc[0]
        weekly = float(offer["capacity_per_week"])
        lead = float(offer["lead_days"])

        # The window that matters for one purchase order is the lead time, not a
        # calendar week. Comparing a whole order against a single week of output
        # made every order look impossible, which is a way of saying nothing.
        lead_weeks = max(lead / 7.0, 1.0)
        buildable = weekly * lead_weeks
        strain = quantity / buildable if buildable else float("inf")

        factors.append({
            "factor": "Order size against capacity",
            "value": round(strain, 3),
            "contribution": round(min(strain, 3.0) / 3, 4),
            "explanation": (
                f"{quantity:,.0f} units is {_format_multiple(strain)} what this supplier can make "
                f"in the {lead:.0f}-day lead time — about {buildable:,.0f} units at their usual "
                f"rate of {weekly:,.0f} a week."
            ),
        })

        factors.append({
            "factor": "Lead time",
            "value": round(lead, 1),
            "contribution": round(min(lead / 365, 1.0) / 4, 4),
            "explanation": f"Quoted lead time is {lead:.0f} days.",
        })
    else:
        factors.append({
            "factor": "Approval",
            "value": None,
            "contribution": 0.5,
            "explanation": (
                f"This supplier is not on the approved list for {material_id}"
                + (f" at {plant_id}" if plant_id else "")
                + ". Qualification would be needed before ordering."
            ),
        })

    if not measured:
        factors.append({
            "factor": "No trading history",
            "value": None,
            "contribution": 0.3,
            "explanation": (
                "We have no delivery record with this supplier, so the score is the population "
                "average rather than a prediction about them."
            ),
        })

    strain = next(
        (f["value"] for f in factors if f["factor"] == "Order size against capacity"), None
    )
    level, advice = _verdict(delay_p, strain)
    origin = str(supplier.get("origin", "real"))
    source = "measured from their own delivery record" if measured else "the population average"

    explanation = (
        f"{supplier.get('name', supplier['supplier_id'])} has a {delay_p:.0%} chance of delivering "
        f"this order late and a {quality_p:.0%} chance of a quality problem. The delay figure is "
        f"{source} and scores the supplier, not the size of this order — order size is checked "
        f"separately, below. {advice}"
    )
    if origin == "synthetic":
        explanation += " This is a generated supplier, included to make the comparison realistic."

    factors.sort(key=lambda f: f["contribution"], reverse=True)
    return {
        "supplier_id": str(supplier["supplier_id"]),
        "supplier_name": str(supplier.get("name", supplier["supplier_id"])),
        "delay_probability": round(delay_p, 4),
        "quality_probability": round(quality_p, 4),
        "has_measured_risk": measured,
        "verdict": level,
        "explanation": explanation,
        "top_factors": factors[:4],
    }
