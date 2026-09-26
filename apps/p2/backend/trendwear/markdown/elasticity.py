"""How much extra a discount sells — measured where possible, stated where not.

The design assumed we could fit a price-elasticity curve from the discount
column. **We measured it, and we cannot.** In this dataset the correlation
between discount and units sold is 0.036, the log-log slope is about -0.07, and
average weekly units move from 1,003 at full price to 1,105 at the deepest
discount: roughly 10%, and not monotonic in between. A real apparel markdown
moves far more volume than that.

So this module does two things, and keeps them apart:

1. **Fits the elasticity that is actually in the data** and reports it, together
   with how much of the variation it explains. On this dataset that is close to
   nothing, and the module says so.
2. **Falls back to a stated assumption** when the fit is too weak to use, the
   same way the PR1 risk models fall back to an observed rate when a label does
   not support a model. The assumed value is -1.8, in the middle of the range
   published for apparel, and it is recorded in `docs/assumptions.md` and shown
   on screen wherever a markdown recommendation appears.

The alternative — quietly fitting a curve to noise and presenting the result as
measured — would give a panel a number that falls apart under one question.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Published apparel price elasticities cluster between -1.2 and -2.5. We use the
# middle, and label every recommendation that rests on it.
ASSUMED_ELASTICITY = -1.8

# Below this R-squared the fit explains too little to plan with.
MIN_R_SQUARED = 0.30
MIN_OBSERVATIONS = 12


@dataclass(frozen=True)
class Elasticity:
    """A price elasticity, and whether it came from the data or from us."""

    value: float
    source: str                 # "measured" or "assumed"
    r_squared: float
    observations: int
    reason: str

    @property
    def is_measured(self) -> bool:
        return self.source == "measured"


def _fit_log_log(discounts: np.ndarray, units: np.ndarray) -> tuple[float, float]:
    """Slope of log(units) against log(price ratio), and its R-squared."""
    price_ratio = np.clip(1 - discounts, 0.05, 1.0)
    x = np.log(price_ratio)
    y = np.log(np.clip(units, 1, None))

    if len(x) < 2 or np.allclose(x, x[0]):
        return 0.0, 0.0

    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    residual = float(np.sum((y - predicted) ** 2))
    total = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - residual / total if total > 0 else 0.0
    return float(slope), float(max(r_squared, 0.0))


def fit(weekly: pd.DataFrame, category: str | None = None) -> Elasticity:
    """Fit the elasticity for a category, or fall back to the stated assumption."""
    data = weekly if category is None else weekly[weekly.get("category") == category]
    data = data[data["units"] > 0]

    if len(data) < MIN_OBSERVATIONS:
        return Elasticity(
            value=ASSUMED_ELASTICITY,
            source="assumed",
            r_squared=0.0,
            observations=len(data),
            reason=(
                f"only {len(data)} observations, fewer than the {MIN_OBSERVATIONS} needed "
                "to fit a response"
            ),
        )

    slope, r_squared = _fit_log_log(
        data["discount_pct"].to_numpy(), data["units"].to_numpy()
    )

    if r_squared < MIN_R_SQUARED or slope >= 0:
        return Elasticity(
            value=ASSUMED_ELASTICITY,
            source="assumed",
            r_squared=round(r_squared, 4),
            observations=len(data),
            reason=(
                f"the fitted response explains only {r_squared:.1%} of the variation "
                f"(slope {slope:.2f}), so it is too weak to plan with. Using the published "
                f"apparel elasticity of {ASSUMED_ELASTICITY}, stated in the assumptions."
            ),
        )

    return Elasticity(
        value=round(slope, 3),
        source="measured",
        r_squared=round(r_squared, 4),
        observations=len(data),
        reason=(
            f"fitted on {len(data)} weeks, explaining {r_squared:.1%} of the variation"
        ),
    )


def fit_by_category(weekly: pd.DataFrame, styles: pd.DataFrame) -> dict[str, Elasticity]:
    """One elasticity per category, each labelled measured or assumed."""
    joined = weekly.merge(styles[["style_id", "category"]], on="style_id", how="left")
    return {
        str(category): fit(group)
        for category, group in joined.groupby("category")
        if pd.notna(category)
    }


def uplift(elasticity: Elasticity, depth: float) -> float:
    """How many times more units a discount of ``depth`` is expected to sell.

    A constant-elasticity response: cutting price to (1 - depth) of full
    multiplies volume by (1 - depth) raised to the elasticity. At -1.8, a 20%
    cut sells about 1.5 times the units.
    """
    if not 0 <= depth < 1:
        raise ValueError("markdown depth must sit between 0 and 1")
    if depth == 0:
        return 1.0
    return float((1 - depth) ** elasticity.value)
