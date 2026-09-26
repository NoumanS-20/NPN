"""When to mark a style down, and by how much.

The use case asks for markdown timing "based on in-season sell-through signals",
so the trigger is sell-through against target rather than a fixed sale date.

The logic a merchandiser would recognise:

1. Project where the style lands if nothing changes — current rate, weeks left.
2. If the projection clears the sell-through target, recommend nothing. A
   markdown on a style that will sell out anyway is margin given away.
3. Otherwise search the weeks remaining and the depths available, and pick the
   pair that recovers the most margin.

Marking down earlier sells more units at a smaller discount; marking down later
keeps full price longer but needs a deeper cut and leaves fewer weeks to work.
That tension is the whole decision, and the grid search makes it explicit rather
than hiding it in a rule.

**The decision is priced on revenue, not margin.** By the time a markdown is on
the table the season's buy is made and the cost is sunk, so the only question is
how much revenue the stock realises: full price now, a discount later, or salvage
at the end. Pricing it on margin instead — as an earlier version did — makes
every markdown look like a loss, because margin per unit falls faster than volume
rises, and the model recommends nothing while the stockroom fills up.

Every recommendation carries whether its elasticity was **measured or assumed**.
On this dataset it is assumed, because the discount column carries no usable
signal — see `elasticity.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trendwear.markdown.elasticity import Elasticity, uplift

DEPTHS = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50)


@dataclass(frozen=True)
class MarkdownRecommendation:
    style_id: str
    recommend: bool
    week: int | None
    depth_pct: float
    projected_sell_through: float
    projected_with_markdown: float
    target_sell_through: float
    margin_no_markdown: float
    margin_with_markdown: float
    margin_recovered: float
    margin_vs_end_of_season: float
    elasticity: float
    elasticity_source: str
    reason: str


def project_sell_through(
    sold_to_date: float,
    weekly_rate: float,
    weeks_left: int,
    buy_quantity: float,
) -> float:
    """Where the style lands if nothing changes."""
    if buy_quantity <= 0:
        return 0.0
    return float(min((sold_to_date + weekly_rate * weeks_left) / buy_quantity, 1.0))


# What unsold stock fetches when the season closes: a jobber pays a fraction of
# the ticket price, not of cost. Apparel clearance typically lands near a fifth.
SALVAGE_SHARE_OF_PRICE = 0.20


def _revenue(units: float, price: float, depth: float) -> float:
    """Revenue from units sold at a given discount."""
    return float(units * price * (1 - depth))


def _salvage(unsold: float, price: float) -> float:
    """What is left at the end of the season, cleared at salvage."""
    return float(unsold * price * SALVAGE_SHARE_OF_PRICE)


def recommend(
    style: pd.Series,
    sold_to_date: float,
    weekly_rate: float,
    weeks_left: int,
    buy_quantity: float,
    elasticity: Elasticity,
    depths: tuple[float, ...] = DEPTHS,
) -> MarkdownRecommendation:
    """The best week and depth, or no markdown at all."""
    price = float(style["price"])
    target = float(style.get("target_sell_through", 0.85))

    baseline_projection = project_sell_through(
        sold_to_date, weekly_rate, weeks_left, buy_quantity
    )

    remaining = max(buy_quantity - sold_to_date, 0.0)
    baseline_units = min(weekly_rate * weeks_left, remaining)
    baseline_margin = (
        _revenue(baseline_units, price, 0.0)
        + _salvage(remaining - baseline_units, price)
    )

    if baseline_projection >= target:
        return MarkdownRecommendation(
            style_id=str(style["style_id"]),
            recommend=False,
            week=None,
            depth_pct=0.0,
            projected_sell_through=round(baseline_projection, 4),
            projected_with_markdown=round(baseline_projection, 4),
            target_sell_through=target,
            margin_no_markdown=round(baseline_margin, 2),
            margin_with_markdown=round(baseline_margin, 2),
            margin_recovered=0.0,
            margin_vs_end_of_season=0.0,
            elasticity=elasticity.value,
            elasticity_source=elasticity.source,
            reason=(
                f"Projected to reach {baseline_projection:.0%} sell-through against a "
                f"{target:.0%} target. A markdown here would give away margin on units "
                "that will sell anyway."
            ),
        )

    best = None
    for start_week in range(1, max(weeks_left, 1) + 1):
        for depth in depths:
            if depth == 0:
                continue

            full_price_weeks = start_week - 1
            markdown_weeks = weeks_left - full_price_weeks

            units_full = min(weekly_rate * full_price_weeks, remaining)
            units_marked = min(
                weekly_rate * uplift(elasticity, depth) * markdown_weeks,
                remaining - units_full,
            )
            unsold = max(remaining - units_full - units_marked, 0.0)

            margin = (
                _revenue(units_full, price, 0.0)
                + _revenue(units_marked, price, depth)
                + _salvage(unsold, price)
            )

            if best is None or margin > best["margin"]:
                best = {
                    "week": start_week,
                    "depth": depth,
                    "margin": margin,
                    "sell_through": min(
                        (sold_to_date + units_full + units_marked) / buy_quantity, 1.0
                    ),
                }

    # The alternative everyone reaches for: one deep cut at the end of the season.
    full_price_units = min(weekly_rate * (weeks_left - 1), remaining)
    end_units = min(weekly_rate * uplift(elasticity, 0.5), remaining - full_price_units)
    end_of_season_margin = (
        _revenue(full_price_units, price, 0.0)
        + _revenue(end_units, price, 0.5)
        + _salvage(remaining - full_price_units - end_units, price)
    )

    recovered = best["margin"] - baseline_margin
    return MarkdownRecommendation(
        style_id=str(style["style_id"]),
        recommend=recovered > 0,
        week=best["week"],
        depth_pct=best["depth"],
        projected_sell_through=round(baseline_projection, 4),
        projected_with_markdown=round(best["sell_through"], 4),
        target_sell_through=target,
        margin_no_markdown=round(baseline_margin, 2),
        margin_with_markdown=round(best["margin"], 2),
        margin_recovered=round(recovered, 2),
        margin_vs_end_of_season=round(best["margin"] - end_of_season_margin, 2),
        elasticity=elasticity.value,
        elasticity_source=elasticity.source,
        reason=(
            f"Tracking to {baseline_projection:.0%} against a {target:.0%} target. "
            f"A {best['depth']:.0%} markdown from week {best['week']} lifts the projection to "
            f"{best['sell_through']:.0%} and realises {recovered:,.0f} more revenue than "
            "leaving it at full price."
            + ("" if elasticity.is_measured else
               f" Based on an assumed elasticity of {elasticity.value}, because the data "
               "shows no usable price response.")
        ),
    )


def recommend_all(
    styles: pd.DataFrame,
    weekly: pd.DataFrame,
    elasticities: dict[str, Elasticity],
    default_elasticity: Elasticity,
    season_weeks: int = 13,
) -> pd.DataFrame:
    """A recommendation per style, from its own sell-through."""
    latest_week = int(weekly["week_index"].max())
    rows = []

    for style in styles.itertuples():
        history = weekly[weekly["style_id"] == style.style_id]
        if history.empty:
            continue

        recent = history[history["week_index"] > latest_week - season_weeks]
        sold = float(recent["units"].sum())
        rate = float(recent["units"].mean()) if len(recent) else 0.0
        weeks_elapsed = len(recent)
        weeks_left = max(season_weeks - weeks_elapsed, 1)

        # The season's buy: what a merchandiser committed to before it started.
        buy_quantity = float(style.baseline_weekly_units) * season_weeks

        elasticity = elasticities.get(style.category, default_elasticity)
        result = recommend(
            pd.Series({
                "style_id": style.style_id,
                "price": style.price,
                "cost": style.cost,
                "target_sell_through": style.target_sell_through,
            }),
            sold_to_date=sold,
            weekly_rate=rate,
            weeks_left=weeks_left,
            buy_quantity=buy_quantity,
            elasticity=elasticity,
        )
        rows.append(result.__dict__ | {"category": style.category, "name": style.name})

    return pd.DataFrame(rows)


def summarise(recommendations: pd.DataFrame) -> dict[str, float | int | str]:
    if recommendations.empty:
        return {"styles": 0, "marked_down": 0}

    flagged = recommendations[recommendations["recommend"]]
    return {
        "styles": int(len(recommendations)),
        "marked_down": int(len(flagged)),
        "median_depth": round(float(flagged["depth_pct"].median()), 3) if len(flagged) else 0.0,
        "median_week": int(flagged["week"].median()) if len(flagged) else 0,
        "margin_recovered": round(float(flagged["margin_recovered"].sum()), 2),
        "vs_end_of_season": round(float(flagged["margin_vs_end_of_season"].sum()), 2),
        "elasticity_source": (
            "assumed" if (recommendations["elasticity_source"] == "assumed").all() else "mixed"
        ),
        "styles_on_track": int((~recommendations["recommend"]).sum()),
        "median_projected_sell_through": round(
            float(recommendations["projected_sell_through"].median()), 4
        ),
    }


def price_ladder(elasticity: Elasticity, depths: tuple[float, ...] = DEPTHS) -> pd.DataFrame:
    """What each depth is expected to do to volume — shown beside the advice."""
    return pd.DataFrame([
        {
            "depth_pct": depth,
            "units_multiplier": round(uplift(elasticity, depth), 3),
            "revenue_multiplier": round(uplift(elasticity, depth) * (1 - depth), 3),
        }
        for depth in depths
    ])


def clearance_risk(recommendations: pd.DataFrame) -> pd.DataFrame:
    """Styles furthest from their target — where the money is leaking."""
    if recommendations.empty:
        return recommendations
    gap = recommendations["target_sell_through"] - recommendations["projected_sell_through"]
    return (
        recommendations.assign(gap=np.round(gap, 4))
        .sort_values("gap", ascending=False)
        .head(10)
    )
