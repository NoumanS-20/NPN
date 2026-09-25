"""Metric helpers shared by both applications.

Every model in this repository reports the same dictionary shape, so the model
panels, the module guides and the final presentation all quote identical
definitions. Nothing here knows anything about suppliers or styles.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def classification_report_dict(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    threshold: float = 0.5,
) -> dict[str, float]:
    """Precision, recall, F1, ROC-AUC and PR-AUC for a binary classifier.

    ``y_prob`` holds predicted probabilities, not labels. PR-AUC is reported
    alongside ROC-AUC because our positive classes are rare, and ROC-AUC alone
    flatters a model on imbalanced data.
    """
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)

    if y_true.size != y_prob.size:
        raise ValueError("y_true and y_prob must be the same length")
    if np.unique(y_true).size < 2:
        raise ValueError("metrics need both classes present in y_true")

    y_pred = (y_prob >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "support": int(y_true.size),
        "positive_rate": float(y_true.mean()),
        "threshold": float(threshold),
    }


def regression_report_dict(actual: ArrayLike, predicted: ArrayLike) -> dict[str, float]:
    """WAPE, MAPE and bias for a forecast.

    WAPE leads because it stays meaningful when some periods sell nothing, which
    MAPE does not. Bias is signed, so a plan that consistently over-forecasts is
    visible rather than hidden inside an absolute error.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    if actual.size != predicted.size:
        raise ValueError("actual and predicted must be the same length")
    if actual.size == 0:
        raise ValueError("cannot score an empty series")

    denominator = np.abs(actual).sum()
    if denominator == 0:
        raise ValueError("cannot compute WAPE when every actual value is zero")

    error = predicted - actual
    non_zero = actual != 0
    mape = (
        float(np.mean(np.abs(error[non_zero] / actual[non_zero])))
        if non_zero.any()
        else float("nan")
    )

    return {
        "wape": float(np.abs(error).sum() / denominator),
        "mape": mape,
        "bias": float(error.sum() / denominator),
        "mae": float(np.abs(error).mean()),
        "support": int(actual.size),
    }


def compare_to_baseline(model: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    """Deltas between a model and its baseline, keyed ``<metric>_delta``.

    Reported next to every model so a number is never quoted without the thing
    it is meant to beat.
    """
    shared = set(model) & set(baseline)
    return {f"{k}_delta": float(model[k] - baseline[k]) for k in sorted(shared)}
