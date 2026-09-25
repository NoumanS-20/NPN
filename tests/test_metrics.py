"""Shared metric and split helpers used by both applications."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pyshared.metrics import classification_report_dict, regression_report_dict
from pyshared.timeutil import time_split


def test_perfect_classifier_scores_one() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.9, 0.8])
    out = classification_report_dict(y, p)
    assert out["f1"] == 1.0
    assert out["roc_auc"] == 1.0
    assert out["support"] == 4
    assert out["positive_rate"] == 0.5


def test_classification_report_has_every_required_key() -> None:
    y = np.array([0, 1, 0, 1, 1])
    p = np.array([0.2, 0.7, 0.4, 0.9, 0.3])
    out = classification_report_dict(y, p)
    assert {"precision", "recall", "f1", "roc_auc", "pr_auc", "support",
            "positive_rate", "threshold"} <= set(out)


def test_classification_report_rejects_a_single_class() -> None:
    y = np.array([1, 1, 1])
    p = np.array([0.6, 0.7, 0.8])
    with pytest.raises(ValueError, match="both classes"):
        classification_report_dict(y, p)


def test_regression_report_computes_wape_and_bias() -> None:
    actual = np.array([100.0, 100.0])
    predicted = np.array([110.0, 90.0])
    out = regression_report_dict(actual, predicted)
    assert out["wape"] == pytest.approx(0.1)
    assert out["bias"] == pytest.approx(0.0)
    assert out["support"] == 2


def test_time_split_is_chronological_and_keeps_every_row() -> None:
    df = pd.DataFrame({
        "d": pd.to_datetime(["2020-03-01", "2020-01-01", "2020-02-01", "2020-04-01"]),
        "v": [3, 1, 2, 4],
    })
    train, test = time_split(df, "d", test_fraction=0.25)
    assert len(train) == 3 and len(test) == 1
    assert train["d"].max() <= test["d"].min()
    assert len(train) + len(test) == len(df)


def test_time_split_never_returns_an_empty_side() -> None:
    df = pd.DataFrame({"d": pd.to_datetime(["2020-01-01", "2020-01-02"]), "v": [1, 2]})
    train, test = time_split(df, "d", test_fraction=0.01)
    assert len(train) >= 1 and len(test) >= 1
