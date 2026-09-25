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


def _verdict(probability: float) -> tuple[str, str]:
    if probability >= _HIGH_THRESHOLD:
        return "high", (
            "Hold for review. Consider splitting this order or bringing the date forward."
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
        capacity = float(offer["capacity_per_week"])
        utilisation = quantity / capacity if capacity else 0.0
        factors.append({
            "factor": "Order size against capacity",
            "value": round(utilisation, 3),
            "contribution": round(min(utilisation, 1.5) / 3, 4),
            "explanation": (
                f"{quantity:,.0f} units is {utilisation:.0%} of this supplier's usual weekly "
                f"output for this material."
            ),
        })

        lead = float(offer["lead_days"])
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

    level, advice = _verdict(delay_p)
    origin = str(supplier.get("origin", "real"))
    source = "measured from their own delivery record" if measured else "the population average"

    explanation = (
        f"{supplier.get('name', supplier['supplier_id'])} has a {delay_p:.0%} chance of delivering "
        f"this order late and a {quality_p:.0%} chance of a quality problem. The delay figure is "
        f"{source}. {advice}"
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
