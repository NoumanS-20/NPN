"""The delay-risk model: will this supplier deliver this order late?

This is the model the use case names directly — "predict potential delivery
delays before PO release" — and its output feeds the allocation objective, so a
weak model does not merely look bad on a slide, it produces worse sourcing.

The thresholds asserted here are floors we measured, not targets we hope for. If
a change drops a score below its floor the build fails, and if a genuine
improvement raises it the floor moves up deliberately.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from supplyguard.config import RAW_SCMS
from supplyguard.etl.scms import load_scms
from supplyguard.features.build import build_order_features
from supplyguard.risk.delay import benchmark, select, train


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return build_order_features(load_scms(RAW_SCMS))


@pytest.fixture(scope="module")
def model(features: pd.DataFrame):
    return train(features)


def test_model_beats_both_baselines(model) -> None:
    """A model that cannot beat 'assume the supplier repeats itself' is not worth shipping."""
    assert model.metrics["pr_auc"] > model.metrics["baseline_prior_pr_auc"]
    assert model.metrics["pr_auc"] > model.metrics["baseline_majority_pr_auc"]


def test_discrimination_meets_the_measured_floor(model) -> None:
    assert model.metrics["roc_auc"] > 0.70
    assert model.metrics["pr_auc"] > 0.25


def test_the_split_is_chronological(model) -> None:
    assert model.metrics["train_end_date"] <= model.metrics["test_start_date"]


def test_metrics_are_measured_on_real_rows_only(model, features: pd.DataFrame) -> None:
    real = features[features["origin"] == "real"]
    assert model.metrics["support"] < len(real)
    assert model.metrics["support"] > 0


def test_probabilities_are_probabilities(model, features: pd.DataFrame) -> None:
    probabilities = model.predict_proba(features.head(500))
    assert probabilities.shape == (500,)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()


def test_probabilities_are_calibrated_against_observed_rates(model, features: pd.DataFrame) -> None:
    """A probability the optimiser multiplies by cost must mean what it says."""
    probabilities = model.predict_proba(features)
    predicted_rate = float(probabilities.mean())
    observed_rate = float(features["is_late"].mean())
    assert abs(predicted_rate - observed_rate) < 0.06


def test_feature_importance_is_reported(model) -> None:
    importance = model.feature_importance
    assert importance
    assert all(value >= 0 for value in importance.values())
    assert sum(importance.values()) > 0


def test_benchmark_compares_three_candidates(features: pd.DataFrame) -> None:
    """Ajmal's suggestion: show the model choice, do not assert it."""
    results = benchmark(features)
    assert set(results) == {"logistic_regression", "random_forest", "xgboost"}
    for name, metrics in results.items():
        assert {"precision", "recall", "f1", "roc_auc", "pr_auc"} <= set(metrics), name


def test_selection_prefers_the_simpler_model_when_it_is_as_good() -> None:
    results = {
        "logistic_regression": {"pr_auc": 0.40},
        "random_forest": {"pr_auc": 0.405},
        "xgboost": {"pr_auc": 0.407},
    }
    assert select(results, tolerance=0.01) == "logistic_regression"


def test_selection_picks_the_strongest_when_the_gap_is_real() -> None:
    results = {
        "logistic_regression": {"pr_auc": 0.30},
        "random_forest": {"pr_auc": 0.35},
        "xgboost": {"pr_auc": 0.45},
    }
    assert select(results, tolerance=0.01) == "xgboost"


def test_training_is_reproducible(features: pd.DataFrame) -> None:
    first = train(features)
    second = train(features)
    assert first.metrics["pr_auc"] == second.metrics["pr_auc"]
    assert np.allclose(
        first.predict_proba(features.head(100)), second.predict_proba(features.head(100))
    )


def test_model_round_trips_through_disk(model, tmp_path, features: pd.DataFrame) -> None:
    """The demo loads saved artifacts; it never trains."""
    path = tmp_path / "delay.joblib"
    model.save(path)
    loaded = type(model).load(path)
    assert loaded.metrics == model.metrics
    sample = features.head(50)
    assert np.allclose(loaded.predict_proba(sample), model.predict_proba(sample))
