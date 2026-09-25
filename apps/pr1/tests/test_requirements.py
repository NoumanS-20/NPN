"""Plants and the material requirement plan.

The official data spec asks PR1 for a "material demand forecast (by SKU/plant)".
We supply it as a deterministic roll-up of historical consumption, not a trained
model: forecasting belongs to P2, and the mentor requires the two solutions not
to overlap. One test below enforces exactly that.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from supplyguard.config import PLANNING_HORIZON_WEEKS, RAW_SCMS, TOP_PLANTS
from supplyguard.etl.plants import derive_plants
from supplyguard.etl.requirements import build_plan
from supplyguard.etl.scms import load_scms

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def orders() -> pd.DataFrame:
    return load_scms(RAW_SCMS)


@pytest.fixture(scope="module")
def plants(orders: pd.DataFrame) -> pd.DataFrame:
    return derive_plants(orders, top_n=TOP_PLANTS)


@pytest.fixture(scope="module")
def plan(orders: pd.DataFrame, plants: pd.DataFrame) -> pd.DataFrame:
    return build_plan(orders, plants, horizon_weeks=PLANNING_HORIZON_WEEKS)


def test_plants_are_the_highest_volume_destinations(plants: pd.DataFrame) -> None:
    assert len(plants) == TOP_PLANTS
    assert plants["plant_id"].is_unique
    assert (plants["historical_volume"] > 0).all()
    assert plants["historical_volume"].is_monotonic_decreasing


def test_requirement_plan_covers_the_whole_horizon(plan: pd.DataFrame) -> None:
    assert plan["week"].nunique() == PLANNING_HORIZON_WEEKS
    counts = plan.groupby(["material_id", "plant_id"]).size()
    assert counts.eq(PLANNING_HORIZON_WEEKS).all()


def test_requirements_are_positive_numbers(plan: pd.DataFrame) -> None:
    assert (plan["required_qty"] > 0).all()
    assert plan["required_qty"].notna().all()


def test_requirements_are_marked_as_derived(plan: pd.DataFrame) -> None:
    assert set(plan["source"].unique()) == {"derived"}


def test_plan_totals_track_historical_consumption(orders: pd.DataFrame, plants: pd.DataFrame) -> None:
    """A year of plan should resemble a year of history, not an invented number."""
    yearly = build_plan(orders, plants, horizon_weeks=52, seasonal=False)
    planned_weekly = yearly["required_qty"].sum() / 52

    covered = orders[orders["plant_id"].isin(plants["plant_id"])] if "plant_id" in orders else orders
    weeks = (covered["promised_date"].max() - covered["promised_date"].min()).days / 7
    historical_weekly = covered["qty"].sum() / weeks

    assert 0.5 < planned_weekly / historical_weekly < 2.0


def test_seasonality_changes_the_shape_but_not_the_scale(
    orders: pd.DataFrame, plants: pd.DataFrame
) -> None:
    flat = build_plan(orders, plants, horizon_weeks=52, seasonal=False)
    seasonal = build_plan(orders, plants, horizon_weeks=52, seasonal=True)
    assert seasonal["required_qty"].std() > flat["required_qty"].std()
    ratio = seasonal["required_qty"].sum() / flat["required_qty"].sum()
    assert 0.8 < ratio < 1.25


def test_plan_is_deterministic(orders: pd.DataFrame, plants: pd.DataFrame) -> None:
    a = build_plan(orders, plants, horizon_weeks=PLANNING_HORIZON_WEEKS)
    b = build_plan(orders, plants, horizon_weeks=PLANNING_HORIZON_WEEKS)
    pd.testing.assert_frame_equal(a, b)


def test_pr1_contains_no_forecasting_model() -> None:
    """The separation rule, enforced.

    PR1 derives requirements from history. Any trained forecaster here would
    duplicate P2's approach, which the mentor ruled against in writing.
    """
    banned = ("LGBMRegressor", "lightgbm", "chronos", "Prophet", "ARIMA", "ExponentialSmoothing")
    for path in (ROOT / "apps" / "pr1" / "backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path} uses a forecasting model ({token})"
