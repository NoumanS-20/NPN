"""Quality and disruption risk.

These two labels come from small files — 517 and 777 orders — and the team agreed
on 25 September that we would verify the labels before promising three models.
So the modules here are allowed to answer "this label does not support a model",
and these tests check that the decision is made on evidence and recorded, rather
than a weak model being shipped with a confident-sounding number.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_PROCUREMENT_KPI, RAW_SUPPLIER_LINES
from supplyguard.etl.procurement_files import load_disruption_orders, load_quality_orders
from supplyguard.risk.disruption import train as train_disruption
from supplyguard.risk.quality import train as train_quality


@pytest.fixture(scope="module")
def quality_orders() -> pd.DataFrame:
    return load_quality_orders(RAW_SUPPLIER_LINES)


@pytest.fixture(scope="module")
def disruption_orders() -> pd.DataFrame:
    return load_disruption_orders(RAW_PROCUREMENT_KPI)


# --- the data ------------------------------------------------------------


def test_quality_file_has_the_measured_shape(quality_orders: pd.DataFrame) -> None:
    assert len(quality_orders) == 517
    assert quality_orders["supplier_id"].nunique() == 44
    assert 0.12 < quality_orders["has_quality_event"].mean() < 0.15      # measured 13.7%


def test_disruption_file_has_the_measured_shape(disruption_orders: pd.DataFrame) -> None:
    assert len(disruption_orders) == 777
    assert disruption_orders["supplier_id"].nunique() == 5
    assert 0.15 < disruption_orders["is_disrupted"].mean() < 0.20        # 136 of 777


def test_both_files_are_labelled_public_synthetic_or_real(
    quality_orders: pd.DataFrame, disruption_orders: pd.DataFrame
) -> None:
    assert set(quality_orders["origin"].unique()) == {"public-synthetic"}
    assert set(disruption_orders["origin"].unique()) == {"real"}


def test_quality_features_are_point_in_time(quality_orders: pd.DataFrame) -> None:
    """Same leakage discipline as the delay model, on a much smaller file."""
    first_orders = quality_orders.sort_values("order_date").groupby("supplier_id").head(1)
    assert first_orders["supplier_prior_quality_rate"].isna().all()


# --- the sufficiency gate ------------------------------------------------


def test_quality_model_reports_whether_the_label_supports_it(quality_orders: pd.DataFrame) -> None:
    model = train_quality(quality_orders)
    assert isinstance(model.metrics["label_sufficient"], bool)
    assert model.metrics["sufficiency_reason"]
    assert "pr_auc" in model.metrics


def test_disruption_model_reports_whether_the_label_supports_it(
    disruption_orders: pd.DataFrame,
) -> None:
    model = train_disruption(disruption_orders)
    assert isinstance(model.metrics["label_sufficient"], bool)
    assert model.metrics["sufficiency_reason"]


def test_an_insufficient_label_falls_back_to_the_observed_rate(
    quality_orders: pd.DataFrame,
) -> None:
    """A weak model must not be dressed up: fall back to the supplier's own rate."""
    model = train_quality(quality_orders)
    probabilities = model.predict_proba(quality_orders)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    if not model.metrics["label_sufficient"]:
        assert model.metrics["fallback"] == "supplier_observed_rate"


def test_predictions_track_the_observed_rate(quality_orders: pd.DataFrame) -> None:
    model = train_quality(quality_orders)
    predicted = float(model.predict_proba(quality_orders).mean())
    observed = float(quality_orders["has_quality_event"].mean())
    assert abs(predicted - observed) < 0.08


def test_disruption_predictions_track_the_observed_rate(
    disruption_orders: pd.DataFrame,
) -> None:
    model = train_disruption(disruption_orders)
    predicted = float(model.predict_proba(disruption_orders).mean())
    observed = float(disruption_orders["is_disrupted"].mean())
    assert abs(predicted - observed) < 0.08


def test_models_round_trip_through_disk(quality_orders: pd.DataFrame, tmp_path) -> None:
    model = train_quality(quality_orders)
    path = tmp_path / "quality.joblib"
    model.save(path)
    loaded = type(model).load(path)
    assert loaded.metrics == model.metrics


def test_training_is_reproducible(disruption_orders: pd.DataFrame) -> None:
    first = train_disruption(disruption_orders)
    second = train_disruption(disruption_orders)
    assert first.metrics["pr_auc"] == second.metrics["pr_auc"]
