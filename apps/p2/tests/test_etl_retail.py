"""P2 data loading: real clothing sales, generated styles, and the network.

The numbers here were measured from the file on 26 September 2026. Two of them
are findings rather than facts about the code, and they are asserted so a change
in the data cannot quietly invalidate what we say on stage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from trendwear.config import RAW_RETAIL, SEED, TARGET_STYLE_COUNT
from trendwear.etl.retail import (
    launch_curve,
    load_daily,
    load_weekly_sales,
    load_weekly_store_sales,
    price_response,
)
from trendwear.etl.synthesize import (
    build_network,
    build_style_catalogue,
    simulate_sales,
)


@pytest.fixture(scope="module")
def daily() -> pd.DataFrame:
    return load_daily(RAW_RETAIL)


@pytest.fixture(scope="module")
def weekly() -> pd.DataFrame:
    return load_weekly_sales(RAW_RETAIL)


@pytest.fixture(scope="module")
def catalogue(weekly: pd.DataFrame) -> pd.DataFrame:
    return build_style_catalogue(weekly, n_styles=TARGET_STYLE_COUNT, seed=SEED)


# --- the real data --------------------------------------------------------


def test_only_clothing_is_loaded(daily: pd.DataFrame) -> None:
    assert len(daily) == 14_626
    assert daily["style_id"].nunique() == 20
    assert daily["store_id"].nunique() == 5


def test_weekly_grain_is_style_and_week(weekly: pd.DataFrame) -> None:
    assert not weekly.duplicated(subset=["style_id", "week_index"]).any()
    assert weekly["style_id"].nunique() == 20
    assert weekly["week_index"].nunique() > 100


def test_demand_is_a_rate_not_a_sum(weekly: pd.DataFrame) -> None:
    """The file samples days, it does not record every day.

    A week with two observations is not a week with two days of trade. Summing
    would make thinly sampled weeks look like a demand collapse, so units are
    observed units scaled to seven days — and the observation count travels with
    the row so a thin week is visible.
    """
    assert "observations" in weekly
    assert (weekly["observations"] > 0).all()
    assert weekly["observations"].median() < 7       # measured: about 5

    row = weekly.iloc[0]
    expected = row["observed_units"] / row["observations"] * 7
    assert row["units"] == pytest.approx(expected, rel=0.01)


def test_weekly_sales_are_labelled_public_synthetic(weekly: pd.DataFrame) -> None:
    assert set(weekly["origin"].unique()) == {"public-synthetic"}


def test_store_level_history_is_available_for_distribution() -> None:
    by_store = load_weekly_store_sales(RAW_RETAIL)
    assert by_store["store_id"].nunique() == 5
    assert len(by_store) > len(load_weekly_sales(RAW_RETAIL))


def test_the_discount_column_carries_almost_no_signal(weekly: pd.DataFrame) -> None:
    """A finding, asserted so it cannot change unnoticed.

    The design assumed a price-elasticity curve could be fitted from this
    column. Measured, discount and units correlate at 0.036 and the log-log
    slope is about -0.07. There is no usable response here, which is why the
    markdown module states its assumption instead of fitting one.
    """
    response = price_response(weekly)
    correlation = float(np.corrcoef(response["discount"], response["mean_units"])[0, 1])
    assert abs(correlation) < 0.3, "the data now shows a price response; revisit markdown"


def test_launch_curve_covers_the_first_weeks(weekly: pd.DataFrame) -> None:
    curve = launch_curve(weekly, weeks=13)
    assert len(curve) == 13
    assert np.isfinite(curve).all()
    assert (curve > 0).all()


# --- the generated catalogue ---------------------------------------------


def test_catalogue_reaches_the_target_and_keeps_the_real_styles(
    catalogue: pd.DataFrame,
) -> None:
    assert len(catalogue) == TARGET_STYLE_COUNT
    assert (catalogue["origin"] == "real").sum() == 20
    assert catalogue["style_id"].is_unique


def test_styles_launch_on_a_six_week_cadence(catalogue: pd.DataFrame) -> None:
    """TrendWear launches a new line every six weeks; 20 styles cannot show that."""
    launches = sorted(catalogue["launch_week"].unique())
    gaps = {b - a for a, b in zip(launches, launches[1:], strict=False)}
    assert gaps == {6}
    assert len(launches) >= 5


def test_generated_prices_track_the_real_ones(catalogue: pd.DataFrame) -> None:
    real = catalogue[catalogue["origin"] == "real"]
    generated = catalogue[catalogue["origin"] == "synthetic"]
    ratio = generated["price"].median() / real["price"].median()
    assert 0.6 < ratio < 1.6


def test_every_style_has_a_fabric_and_a_margin(catalogue: pd.DataFrame) -> None:
    assert catalogue["fabric_id"].notna().all()
    assert (catalogue["fabric_metres"] > 0).all()
    assert (catalogue["margin_pct"] > 0.4).all()


def test_generation_is_deterministic(weekly: pd.DataFrame) -> None:
    first = build_style_catalogue(weekly, seed=SEED)
    second = build_style_catalogue(weekly, seed=SEED)
    pd.testing.assert_frame_equal(first, second)


def test_simulated_sales_start_at_launch(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    sales = simulate_sales(catalogue, weekly, launch_curve(weekly), seed=SEED)
    assert len(sales) > 0

    launches = catalogue.set_index("style_id")["launch_week"]
    first_seen = sales.groupby("style_id")["week_index"].min()
    for style_id, week in first_seen.items():
        assert week >= launches[style_id]


def test_simulated_sales_are_not_suspiciously_smooth(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    """A generated series a model can fit perfectly would flatter the forecast."""
    sales = simulate_sales(catalogue, weekly, launch_curve(weekly), seed=SEED)
    generated_noise = sales.groupby("style_id")["units"].apply(lambda s: s.std() / s.mean())
    real_noise = weekly.groupby("style_id")["units"].apply(lambda s: s.std() / s.mean())
    assert generated_noise.median() > real_noise.median() * 0.4


# --- the network ----------------------------------------------------------


def test_network_has_plants_dcs_stores_and_lanes(catalogue: pd.DataFrame) -> None:
    network = build_network(catalogue, seed=SEED)
    assert set(network) == {"plants", "dcs", "stores", "lanes", "fabric_bom"}
    assert len(network["plants"]) == 3
    assert len(network["stores"]) == 5


def test_every_store_maps_to_one_dc(catalogue: pd.DataFrame) -> None:
    network = build_network(catalogue, seed=SEED)
    assert network["stores"]["store_id"].is_unique
    assert network["stores"]["dc_id"].isin(network["dcs"]["dc_id"]).all()


def test_every_lane_has_a_transit_time_and_a_cost(catalogue: pd.DataFrame) -> None:
    lanes = build_network(catalogue, seed=SEED)["lanes"]
    assert (lanes["transit_days"] > 0).all()
    assert (lanes["cost_per_unit"] > 0).all()
    assert lanes["transit_days"].nunique() > 1, "identical lanes make logistics decorative"


def test_fabric_orders_have_a_minimum(catalogue: pd.DataFrame) -> None:
    bom = build_network(catalogue, seed=SEED)["fabric_bom"]
    assert (bom["fabric_moq_metres"] > 0).all()
    assert len(bom) == len(catalogue)
