"""Describe a plan in words a planner could paste into an email.

Templates filled with the model's own numbers — no language model. The use case
asks for an explainable recommendation, and an explanation that can invent a
number is not one. Every figure here comes from the result object.

An optional language model can rewrite these more fluently; it is off by default
and first on the cut list. The templates are what ships.
"""

from __future__ import annotations

from supplyguard.optimizer.types import AllocationResult


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def explain_allocation(result: AllocationResult, comparison: dict | None = None) -> str:
    """A paragraph describing the plan and what it traded away."""
    if not result.is_optimal or not result.lines:
        return (
            "No plan meets every constraint for this selection. "
            + (result.message or "Relax the concentration cap or the contract limits.")
        )

    units = sum(line.qty for line in result.lines)
    materials = len({line.material_id for line in result.lines})
    generated = sum(line.qty for line in result.lines if line.origin == "synthetic")

    sentences = [
        f"This plan buys {units:,.0f} units of {materials} "
        f"material{'s' if materials != 1 else ''} from {result.suppliers_used} suppliers "
        f"for {_money(result.material_cost)}.",
        f"Allowing for the risk that deliveries arrive late, the total expected cost is "
        f"{_money(result.total_cost)}, and {_pct(result.high_risk_share)} of the volume sits with "
        f"suppliers we judge high risk.",
    ]

    if generated:
        sentences.append(
            f"{_pct(generated / units)} of the volume goes to generated suppliers, which exist to "
            "make the comparison realistic and are labelled as such throughout."
        )

    if comparison:
        historical = comparison.get("historical_mix")
        if historical:
            direction = "less" if historical["total_cost_delta_pct"] < 0 else "more"
            sentences.append(
                f"Against the way this organisation actually bought last year, it costs "
                f"{abs(historical['total_cost_delta_pct']):.1f}% {direction} in total and expects "
                f"{abs(historical['expected_late_delta_pct']):.1f}% "
                f"{'fewer' if historical['expected_late_delta_pct'] < 0 else 'more'} late units."
            )

        cheapest = comparison.get("cheapest_first")
        if cheapest and cheapest["invoice_delta_pct"] > 0:
            sentences.append(
                f"It is {cheapest['invoice_delta_pct']:.1f}% dearer on the invoice than simply "
                f"buying from the cheapest supplier, and carries "
                f"{abs(cheapest['high_risk_delta_pp']):.1f} points less volume on high-risk "
                "suppliers — a trade the concentration and contract rules make for us."
            )

    if result.message:
        sentences.append(f"One note on how it was reached: {result.message.lower()}")

    return " ".join(sentences)


def explain_line(line) -> str:
    """One sentence for a single allocation line."""
    return (
        f"{line.supplier_name} supplies {line.qty:,.0f} units "
        f"({_pct(line.share_of_requirement, 0)} of the requirement) at {line.unit_price:.4f} each, "
        f"with a {_pct(line.delay_probability, 0)} chance of arriving late. {line.reason}"
    )


def explain_scenario(name: str, deltas: dict, feasible: bool, message: str = "") -> str:
    """What a disruption did to the plan."""
    if not feasible:
        return (
            f"{name} leaves the plan unservable. {message} "
            "The approved supplier base cannot absorb this disruption, which is itself "
            "the finding: it tells procurement where the base needs widening."
        )

    cost_pct = deltas["total_cost_pct"]
    parts = [f"{name} raises total cost by {cost_pct:.1f}%"]

    late_pct = deltas.get("expected_late_pct", 0)
    if abs(late_pct) > 0.05:
        direction = "more" if late_pct > 0 else "fewer"
        parts.append(f"with {abs(late_pct):.1f}% {direction} expected late units")

    if deltas.get("suppliers_delta"):
        count = abs(deltas["suppliers_delta"])
        word = "more" if deltas["suppliers_delta"] > 0 else "fewer"
        plural = "s" if count != 1 else ""
        parts.append(f"using {count} {word} supplier{plural}")

    return ", ".join(parts) + ". The plan still meets demand in full."
