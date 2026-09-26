"""Safety stock and the inventory position.

Step 5 of the mentor's flow. The formula is standard, so most of these tests
check the behaviour a planner would expect from it — more buffer for a longer
lead time, more for a higher service level, none where the forecast is perfect —
and one checks the buffer against what actually happened.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from trendwear.config import RAW_RETAIL, SERVICE_LEVEL
from trendwear.etl.retail import load_weekly_sales
from trendwear.inventory.safety_stock import (
    backtest,
    build_position,
    compute,
    reorder_point,
    summarise,
    z_for,
)


def _residuals(sigma: float = 100.0, styles=("A", "B"), n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for style in styles:
        for error in rng.normal(0, sigma, n):
            rows.append({"style_id": style, "error": float(error)})
    return pd.DataFrame(rows)


def test_z_matches_the_service_level() -> None:
    assert z_for(0.95) == pytest.approx(1.645, abs=0.01)
    assert z_for(0.99) == pytest.approx(2.326, abs=0.01)
    assert z_for(0.5) == pytest.approx(0.0, abs=0.01)


def test_an_impossible_service_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        z_for(1.0)


def test_safety_stock_rises_with_the_service_level() -> None:
    residuals = _residuals()
    low = compute(residuals, lead_time_weeks=4, service_level=0.90)
    high = compute(residuals, lead_time_weeks=4, service_level=0.99)
    assert (high["safety_stock"] > low["safety_stock"]).all()


def test_safety_stock_rises_with_the_lead_time() -> None:
    residuals = _residuals()
    short = compute(residuals, lead_time_weeks=1)
    long = compute(residuals, lead_time_weeks=9)
    assert (long["safety_stock"] > short["safety_stock"]).all()


def test_it_uses_the_square_root_of_lead_time_not_the_lead_time() -> None:
    """Errors over several weeks partly cancel; multiplying would double the buffer."""
    residuals = _residuals()
    one = compute(residuals, lead_time_weeks=1)["safety_stock"].iloc[0]
    nine = compute(residuals, lead_time_weeks=9)["safety_stock"].iloc[0]
    assert nine == pytest.approx(one * 3, rel=0.02)      # sqrt(9) = 3, not 9


def test_a_perfect_forecast_needs_no_buffer() -> None:
    residuals = pd.DataFrame({"style_id": ["A"] * 10, "error": [0.0] * 10})
    assert compute(residuals, lead_time_weeks=5)["safety_stock"].iloc[0] == 0.0


def test_a_worse_forecast_earns_a_bigger_buffer() -> None:
    """Safety stock is the price of forecast error, so it must track error."""
    mixed = pd.concat([_residuals(sigma=50, styles=("steady",)),
                       _residuals(sigma=400, styles=("erratic",))])
    result = compute(mixed, lead_time_weeks=5).set_index("style_id")
    assert result.loc["erratic", "safety_stock"] > result.loc["steady", "safety_stock"] * 3


def test_a_style_with_no_history_inherits_the_population_error() -> None:
    """Unmeasured is not the same as reliable."""
    residuals = pd.concat([
        _residuals(sigma=100, styles=("known",)),
        pd.DataFrame({"style_id": ["new"], "error": [12.0]}),
    ])
    result = compute(residuals, lead_time_weeks=5).set_index("style_id")
    assert result.loc["new", "safety_stock"] > 0


def test_reorder_point_is_lead_time_demand_plus_the_buffer() -> None:
    assert reorder_point(100, 4, 250) == 650


def test_position_flags_cover_every_state() -> None:
    weekly = load_weekly_sales(RAW_RETAIL)
    residuals = pd.DataFrame({
        "style_id": weekly["style_id"].unique().repeat(5),
        "error": np.random.default_rng(1).normal(0, 150, weekly["style_id"].nunique() * 5),
    })
    safety = compute(residuals)
    position = build_position(weekly, safety)

    assert set(position["flag"]) <= {"stockout_risk", "below_reorder", "healthy", "overstock"}
    assert len(position) == weekly["style_id"].nunique()


def test_an_empty_shelf_is_always_a_stockout_risk() -> None:
    weekly = load_weekly_sales(RAW_RETAIL).copy()
    weekly.loc[weekly.index[-1], "inventory"] = 0

    residuals = pd.DataFrame({"style_id": weekly["style_id"].unique(), "error": 50.0})
    position = build_position(weekly, compute(residuals))
    empty = position[position["on_hand"] <= 0]
    assert (empty["flag"] == "stockout_risk").all()


def test_backtest_reports_the_service_level_actually_achieved() -> None:
    """A formula that is never checked against the data is a claim, not a result."""
    weekly = load_weekly_sales(RAW_RETAIL)
    residuals = (
        weekly.assign(error=weekly["units"] - weekly.groupby("style_id")["units"].transform("mean"))
        [["style_id", "error"]]
    )
    result = backtest(weekly, compute(residuals, service_level=SERVICE_LEVEL))

    assert result["weeks_observed"] == len(weekly)
    assert 0.0 <= result["breach_rate"] <= 1.0
    assert result["implied_service_level"] > 0.85


def test_summary_counts_every_flag() -> None:
    weekly = load_weekly_sales(RAW_RETAIL)
    residuals = pd.DataFrame({"style_id": weekly["style_id"].unique(), "error": 100.0})
    summary = summarise(build_position(weekly, compute(residuals)))
    assert {"stockout_risk", "below_reorder", "healthy", "overstock"} <= set(summary)
    assert summary["styles"] == weekly["style_id"].nunique()
