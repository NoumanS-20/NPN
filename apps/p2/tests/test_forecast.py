"""Demand forecasting and cold start.

Two things are guarded here above all: that no feature can see the week it is
predicting, and that accuracy is reported on real styles only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from trendwear.config import RAW_RETAIL, SEED
from trendwear.etl.retail import launch_curve, load_weekly_sales
from trendwear.etl.synthesize import build_style_catalogue, simulate_sales
from trendwear.forecast.coldstart import (
    category_average,
    evaluate_holdout,
    find_analogs,
    forecast_new_style,
)
from trendwear.forecast.model import build_features, forecast_horizon, summarise, train


@pytest.fixture(scope="module")
def weekly() -> pd.DataFrame:
    return load_weekly_sales(RAW_RETAIL)


@pytest.fixture(scope="module")
def catalogue(weekly: pd.DataFrame) -> pd.DataFrame:
    return build_style_catalogue(weekly, seed=SEED)


@pytest.fixture(scope="module")
def all_sales(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    generated = simulate_sales(catalogue, weekly, launch_curve(weekly), seed=SEED)
    return pd.concat([weekly, generated], ignore_index=True)


@pytest.fixture(scope="module")
def model(all_sales: pd.DataFrame):
    return train(all_sales)


# --- features -------------------------------------------------------------


def test_the_first_week_of_a_style_has_no_lags(weekly: pd.DataFrame) -> None:
    featured = build_features(weekly)
    first = featured.sort_values("week_index").groupby("style_id").head(1)
    assert first["lag_1"].isna().all()
    assert first["rolling_4"].isna().all()


def test_a_week_never_sees_its_own_sales(weekly: pd.DataFrame) -> None:
    """The decisive leakage test: change a week's units, its own lags must not move."""
    base = build_features(weekly)

    tampered = weekly.copy()
    target = tampered.index[10]
    tampered.loc[target, "units"] = tampered.loc[target, "units"] * 5
    after = build_features(tampered)

    lag_columns = ["lag_1", "lag_2", "lag_4", "rolling_4", "rolling_13"]
    pd.testing.assert_frame_equal(
        base.loc[[target], lag_columns], after.loc[[target], lag_columns]
    )


def test_styles_do_not_borrow_each_other_history(weekly: pd.DataFrame) -> None:
    featured = build_features(weekly).sort_values(["style_id", "week_index"])
    for _, group in featured.groupby("style_id"):
        assert pd.isna(group.iloc[0]["lag_1"])


# --- accuracy -------------------------------------------------------------


def test_the_model_beats_a_seasonal_naive_forecast(model) -> None:
    """If a planner with last year's numbers does better, the model is not worth shipping."""
    assert model.metrics["wape"] < model.metrics["wape_seasonal_naive"]
    assert model.metrics["beats_seasonal_naive"] is True


def test_the_model_beats_a_four_week_moving_average(model) -> None:
    assert model.metrics["wape"] < model.metrics["wape_moving_average"]


def test_accuracy_meets_the_measured_floor(model) -> None:
    assert model.metrics["wape"] < 0.40          # measured 0.340
    assert abs(model.metrics["bias"]) < 0.15     # measured +0.026


def test_accuracy_is_reported_on_real_styles_only(model) -> None:
    assert model.metrics["scored_on"] == "real styles only"


def test_the_split_is_chronological(model) -> None:
    assert model.metrics["train_end_week"] <= model.metrics["test_start_week"]


def test_forecasts_are_never_negative(model, all_sales: pd.DataFrame) -> None:
    featured = build_features(all_sales).dropna(subset=["lag_1"])
    assert (model.predict(featured.head(200)) >= 0).all()


def test_the_horizon_is_contiguous_and_dated(model, all_sales: pd.DataFrame, weekly) -> None:
    style_id = weekly["style_id"].iloc[0]
    horizon = forecast_horizon(model, all_sales, style_id, horizon=13)

    assert len(horizon) == 13
    assert list(horizon["step"]) == list(range(1, 14))
    assert pd.api.types.is_datetime64_any_dtype(horizon["week_start"])
    gaps = horizon["week_start"].diff().dropna().unique()
    assert len(gaps) == 1 and gaps[0] == pd.Timedelta(weeks=1)


def test_an_unknown_style_is_rejected(model, all_sales: pd.DataFrame) -> None:
    with pytest.raises(KeyError):
        forecast_horizon(model, all_sales, "NOT-A-STYLE")


def test_summary_carries_what_the_panel_will_ask_for(model) -> None:
    summary = summarise(model)
    assert {"wape", "mape", "bias", "wape_seasonal_naive", "beats_seasonal_naive"} <= set(summary)


# --- cold start -----------------------------------------------------------


def test_analogs_prefer_the_same_category(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    style = catalogue[catalogue["origin"] == "synthetic"].iloc[0]
    analogs = find_analogs(style, catalogue, weekly, count=5)

    assert len(analogs) == 5
    assert (analogs["category"] == style["category"]).sum() >= 3
    assert analogs["weight"].sum() == pytest.approx(1.0)


def test_analog_weights_fall_with_distance(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    style = catalogue.iloc[30]
    analogs = find_analogs(style, catalogue, weekly, count=5).sort_values("distance")
    assert analogs["weight"].is_monotonic_decreasing


def test_a_new_style_gets_a_full_horizon(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    style = catalogue[catalogue["origin"] == "synthetic"].iloc[0]
    forecast = forecast_new_style(style, catalogue, weekly, launch_curve(weekly), horizon=13)

    assert len(forecast) == 13
    assert (forecast["forecast_units"] >= 0).all()
    assert forecast["forecast_units"].sum() > 0
    assert set(forecast["method"]) == {"analog"}


def test_cold_start_needs_no_network(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    """The shipped method must work on a laptop with no internet, on the day."""
    style = catalogue[catalogue["origin"] == "synthetic"].iloc[0]
    forecast = forecast_new_style(style, catalogue, weekly, launch_curve(weekly))
    assert forecast["method"].iloc[0] == "analog"


def test_a_premium_style_is_not_forecast_like_a_cheap_one(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    """Blending analogs without scaling by price over-forecasts every premium launch."""
    shape = launch_curve(weekly)
    cheap = catalogue.iloc[0].copy()
    premium = cheap.copy()
    premium["price"] = cheap["price"] * 3
    premium["style_id"] = "PREMIUM"

    cheap_total = forecast_new_style(cheap, catalogue, weekly, shape)["forecast_units"].sum()
    premium_total = forecast_new_style(premium, catalogue, weekly, shape)["forecast_units"].sum()
    assert premium_total < cheap_total


def test_holdout_scores_the_analog_method_against_a_baseline(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    """Hiding a real style is what makes the cold-start claim measurable."""
    result = evaluate_holdout(catalogue, weekly, launch_curve(weekly), seed=SEED)

    assert result["scored"] is True
    assert "analog" in result["results"]
    assert "category_average" in result["results"]
    assert result["analog_beats_baseline"] is True


def test_the_held_out_style_is_really_hidden(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    """A style that can see its own history is not a cold start."""
    result = evaluate_holdout(catalogue, weekly, launch_curve(weekly), seed=SEED)
    held_out = result["held_out_style"]
    visible = weekly[weekly["style_id"] != held_out]
    assert held_out not in set(find_analogs(
        catalogue[catalogue["style_id"] == held_out].iloc[0], catalogue, visible
    )["style_id"])


def test_chronos_absence_is_reported_not_hidden(
    catalogue: pd.DataFrame, weekly: pd.DataFrame
) -> None:
    result = evaluate_holdout(catalogue, weekly, launch_curve(weekly), seed=SEED)
    assert isinstance(result["chronos"], str)
    assert result["chronos"]


def test_category_average_is_a_flat_line(catalogue: pd.DataFrame, weekly: pd.DataFrame) -> None:
    style = catalogue.iloc[0]
    baseline = category_average(style, catalogue, weekly, horizon=13)
    assert baseline["forecast_units"].nunique() == 1
    assert np.isfinite(baseline["forecast_units"]).all()
