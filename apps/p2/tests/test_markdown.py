"""Markdown timing and depth.

The test that matters most here is the one asserting we do *not* claim a
measured elasticity on this dataset. The design assumed one could be fitted; it
cannot, and the module has to say so rather than fit a curve to noise.
"""

from __future__ import annotations

import pandas as pd
import pytest
from trendwear.config import RAW_RETAIL, SEED
from trendwear.etl.retail import load_weekly_sales
from trendwear.etl.synthesize import build_style_catalogue
from trendwear.markdown.elasticity import (
    ASSUMED_ELASTICITY,
    Elasticity,
    fit,
    fit_by_category,
    uplift,
)
from trendwear.markdown.recommend import (
    price_ladder,
    project_sell_through,
    recommend,
    recommend_all,
    summarise,
)


@pytest.fixture(scope="module")
def weekly() -> pd.DataFrame:
    return load_weekly_sales(RAW_RETAIL)


@pytest.fixture(scope="module")
def catalogue(weekly: pd.DataFrame) -> pd.DataFrame:
    return build_style_catalogue(weekly, seed=SEED)


def _style(price: float = 100.0, target: float = 0.85) -> pd.Series:
    return pd.Series({
        "style_id": "A", "price": price, "cost": price * 0.4, "target_sell_through": target
    })


def _strong() -> Elasticity:
    return Elasticity(-1.8, "assumed", 0.0, 100, "test fixture")


# --- elasticity -----------------------------------------------------------


def test_this_dataset_does_not_support_a_measured_elasticity(weekly: pd.DataFrame) -> None:
    """The finding, asserted.

    The design assumed a price response could be fitted from the discount
    column. Measured, it explains almost none of the variation, so the module
    must fall back to a stated assumption and label it.
    """
    result = fit(weekly)
    assert result.source == "assumed"
    assert result.value == ASSUMED_ELASTICITY
    assert "too weak to plan with" in result.reason or "observations" in result.reason


def test_a_real_price_response_is_used_when_one_exists() -> None:
    """The fallback must not be a permanent excuse: a clear signal is used."""
    depths = [0.0, 0.1, 0.2, 0.3, 0.4] * 6
    units = [1000 * (1 - d) ** -2.0 for d in depths]
    data = pd.DataFrame({"discount_pct": depths, "units": units})

    result = fit(data)
    assert result.source == "measured"
    assert result.value == pytest.approx(-2.0, abs=0.05)
    assert result.r_squared > 0.9


def test_too_few_observations_fall_back_with_a_reason() -> None:
    data = pd.DataFrame({"discount_pct": [0.0, 0.2], "units": [100, 130]})
    result = fit(data)
    assert result.source == "assumed"
    assert "observations" in result.reason


def test_uplift_follows_the_elasticity() -> None:
    elasticity = _strong()
    assert uplift(elasticity, 0.0) == 1.0
    assert uplift(elasticity, 0.2) == pytest.approx(1.5, abs=0.05)
    assert uplift(elasticity, 0.4) > uplift(elasticity, 0.2)


def test_an_impossible_depth_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        uplift(_strong(), 1.5)


def test_every_category_gets_a_labelled_elasticity(
    weekly: pd.DataFrame, catalogue: pd.DataFrame
) -> None:
    results = fit_by_category(weekly, catalogue)
    assert results
    for category, elasticity in results.items():
        assert elasticity.source in {"measured", "assumed"}, category
        assert elasticity.reason


# --- recommendations ------------------------------------------------------


def test_a_style_on_track_is_left_alone() -> None:
    """A markdown on a style that will sell out anyway is margin given away."""
    result = recommend(_style(), sold_to_date=800, weekly_rate=100, weeks_left=4,
                       buy_quantity=1000, elasticity=_strong())
    assert result.recommend is False
    assert result.depth_pct == 0.0
    assert "sell anyway" in result.reason


def test_a_slow_seller_is_marked_down() -> None:
    result = recommend(_style(), sold_to_date=200, weekly_rate=40, weeks_left=10,
                       buy_quantity=2000, elasticity=_strong())
    assert result.recommend is True
    assert result.depth_pct > 0
    assert result.week is not None


def test_a_deeper_shortfall_earns_a_deeper_cut() -> None:
    mild = recommend(_style(), sold_to_date=600, weekly_rate=80, weeks_left=8,
                     buy_quantity=1500, elasticity=_strong())
    severe = recommend(_style(), sold_to_date=100, weekly_rate=20, weeks_left=8,
                       buy_quantity=1500, elasticity=_strong())
    assert severe.depth_pct >= mild.depth_pct


def test_the_recommendation_beats_doing_nothing() -> None:
    result = recommend(_style(), sold_to_date=200, weekly_rate=40, weeks_left=10,
                       buy_quantity=2000, elasticity=_strong())
    assert result.margin_with_markdown > result.margin_no_markdown
    assert result.margin_recovered > 0


def test_the_recommendation_is_compared_to_an_end_of_season_sale() -> None:
    """The alternative every retailer reaches for, so we have to beat it."""
    result = recommend(_style(), sold_to_date=200, weekly_rate=40, weeks_left=10,
                       buy_quantity=2000, elasticity=_strong())
    assert result.margin_vs_end_of_season != 0


def test_every_recommendation_declares_where_its_elasticity_came_from() -> None:
    result = recommend(_style(), sold_to_date=200, weekly_rate=40, weeks_left=10,
                       buy_quantity=2000, elasticity=_strong())
    assert result.elasticity_source == "assumed"
    assert "assumed elasticity" in result.reason


def test_depth_stays_within_the_ladder() -> None:
    result = recommend(_style(), sold_to_date=50, weekly_rate=10, weeks_left=12,
                       buy_quantity=3000, elasticity=_strong())
    assert 0 < result.depth_pct <= 0.5


def test_projection_is_capped_at_full_sell_through() -> None:
    assert project_sell_through(900, 200, 10, 1000) == 1.0
    assert project_sell_through(0, 0, 10, 1000) == 0.0
    assert project_sell_through(100, 50, 4, 0) == 0.0


def test_recommendations_run_across_the_catalogue(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    elasticities = fit_by_category(weekly, catalogue)
    default = fit(weekly)
    real = catalogue[catalogue["origin"] == "real"]

    results = recommend_all(real, weekly, elasticities, default)
    assert len(results) > 0
    assert set(results["elasticity_source"]) <= {"measured", "assumed"}

    summary = summarise(results)
    assert summary["styles"] == len(results)
    assert summary["marked_down"] <= summary["styles"]


def test_the_price_ladder_shows_the_trade(weekly: pd.DataFrame) -> None:
    ladder = price_ladder(fit(weekly))
    assert len(ladder) == 6
    assert ladder["units_multiplier"].is_monotonic_increasing
    # Deeper cuts sell more units but each one earns less.
    assert ladder["revenue_multiplier"].iloc[-1] < ladder["units_multiplier"].iloc[-1]
