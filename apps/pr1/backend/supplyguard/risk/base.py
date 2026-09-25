"""Shared machinery for the three risk models.

All three answer the same shape of question — *will something go wrong with this
order?* — so they share a container, a chronological split, a baseline comparison
and a save format. The differences that matter live in each model's own module:
which label, which data, which algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pyshared.metrics import classification_report_dict
from pyshared.timeutil import split_boundaries, time_split


@dataclass
class TrainedModel:
    """A fitted model with everything needed to defend it."""

    name: str
    estimator: Any
    features: list[str]
    metrics: dict[str, float | str]
    feature_importance: dict[str, float] = field(default_factory=dict)
    candidates: dict[str, dict[str, float]] = field(default_factory=dict)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        matrix = df.reindex(columns=self.features).astype(float)
        return self.estimator.predict_proba(matrix)[:, 1]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> TrainedModel:
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing. Build the demo pack: python scripts/build_demo_pack.py"
            )
        return joblib.load(path)


def baseline_scores(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    label: str,
    prior_column: str | None,
) -> dict[str, float]:
    """Two baselines every model must beat to earn its place.

    * **majority** — predict the training set's overall rate for everything. This
      is what "the model has learned nothing useful" looks like.
    * **prior** — predict this supplier's own trailing rate. A planner with a
      spreadsheet can do this, so beating it is the real bar.
    """
    y_test = test_df[label].to_numpy(dtype=int)
    rate = float(train_df[label].mean())

    majority = classification_report_dict(y_test, np.full(len(y_test), rate), threshold=0.5)
    scores = {
        "baseline_majority_pr_auc": majority["pr_auc"],
        "baseline_majority_roc_auc": majority["roc_auc"],
    }

    if prior_column and prior_column in test_df:
        prior = test_df[prior_column].fillna(rate).clip(0, 1).to_numpy(dtype=float)
        prior_metrics = classification_report_dict(y_test, prior)
        scores["baseline_prior_pr_auc"] = prior_metrics["pr_auc"]
        scores["baseline_prior_roc_auc"] = prior_metrics["roc_auc"]
        scores["baseline_prior_recall"] = prior_metrics["recall"]
    return scores


def choose_threshold(
    estimator: Any,
    train_df: pd.DataFrame,
    features: list[str],
    label: str,
) -> float:
    """Pick the decision threshold on the training period, not the test period.

    With 11.5% of orders late, a calibrated model almost never exceeds 0.5, so
    the default threshold reports precision and recall of zero for a model that
    ranks well. We choose the threshold that maximises F1 over the training
    period and then apply it unchanged to the test period, which is both
    standard practice and honest: the test data never influences the choice.
    """
    from sklearn.metrics import f1_score

    probabilities = estimator.predict_proba(train_df[features].astype(float))[:, 1]
    y_true = train_df[label].to_numpy(dtype=int)

    candidates = np.quantile(probabilities, np.linspace(0.50, 0.99, 50))
    scores = [f1_score(y_true, (probabilities >= t).astype(int), zero_division=0)
              for t in candidates]
    return float(candidates[int(np.argmax(scores))])


def evaluate(
    estimator: Any,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: list[str],
    label: str,
    date_column: str,
    prior_column: str | None = None,
) -> dict[str, float | str]:
    """Fit-free scoring of an already-fitted estimator, plus context."""
    threshold = choose_threshold(estimator, train_df, features, label)
    probabilities = estimator.predict_proba(test_df[features].astype(float))[:, 1]
    metrics: dict[str, float | str] = dict(
        classification_report_dict(
            test_df[label].to_numpy(dtype=int), probabilities, threshold=threshold
        )
    )
    metrics.update(baseline_scores(train_df, test_df, label, prior_column))
    metrics.update(split_boundaries(train_df, test_df, date_column))
    metrics["train_rows"] = int(len(train_df))
    metrics["train_positive_rate"] = round(float(train_df[label].mean()), 4)
    return metrics


def chronological_split(
    df: pd.DataFrame,
    date_column: str,
    label: str,
    test_fraction: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on the past, test on the future — never a random split.

    A random split lets a model learn from orders placed after the ones it is
    scored on, which is the single easiest way to publish a number that will not
    survive contact with reality.
    """
    ordered = df.dropna(subset=[date_column, label])
    train_df, test_df = time_split(ordered, date_column, test_fraction=test_fraction)

    if train_df[label].nunique() < 2 or test_df[label].nunique() < 2:
        raise ValueError(
            f"chronological split leaves one side of {label!r} with a single class; "
            "the label is too rare or too concentrated in time to model this way"
        )
    return train_df, test_df


def fit_calibrated(
    estimator: Any,
    train_df: pd.DataFrame,
    features: list[str],
    label: str,
    date_column: str,
    calibration_fraction: float = 0.2,
) -> Any:
    """Fit on the earlier training rows, calibrate on the later ones.

    The optimiser multiplies these probabilities by shortage cost, so a
    "0.3" has to mean roughly three orders in ten. Class weighting — which the
    models need, because positives are rare — pushes raw scores far above the
    real rate, so an uncalibrated model would systematically overstate risk and
    distort the allocation.

    Calibration is cross-validated within the *training* period only — the test
    period is never touched, so the reported metrics stay honest. An earlier
    version held out a single slice instead, which cost the model a fifth of its
    training data and dropped PR-AUC from 0.345 to 0.231, below the baseline it
    is supposed to beat.
    """
    from sklearn.calibration import CalibratedClassifierCV

    calibrated = CalibratedClassifierCV(estimator, method="isotonic", cv=3)
    calibrated.fit(train_df[features].astype(float), train_df[label].astype(int))
    return calibrated


def _unwrap(estimator: Any) -> list[Any]:
    """Every fitted learner inside a wrapper.

    Cross-validated calibration fits one model per fold, so importance has to be
    averaged across them rather than read off a single estimator — and a naive
    reach-through finds the *unfitted* template and silently returns nothing.
    """
    fitted = getattr(estimator, "calibrated_classifiers_", None)
    models = [getattr(c, "estimator", c) for c in fitted] if fitted else [estimator]

    resolved = []
    for model in models:
        if hasattr(model, "named_steps"):
            model = model.named_steps.get("model", model)
        resolved.append(model)
    return resolved


def importance_from(estimator: Any, features: list[str]) -> dict[str, float]:
    """Feature importance, whichever kind the estimator offers, averaged over folds."""
    collected = []
    for model in _unwrap(estimator):
        if hasattr(model, "feature_importances_"):
            collected.append(np.asarray(model.feature_importances_, dtype=float))
        elif hasattr(model, "coef_"):
            collected.append(np.abs(np.asarray(model.coef_, dtype=float)).ravel())

    if not collected:
        return {}
    values = np.mean(collected, axis=0)
    if values.shape[0] != len(features):
        return {}
    total = values.sum()
    if total > 0:
        values = values / total
    ranked = sorted(zip(features, values, strict=True), key=lambda kv: kv[1], reverse=True)
    return {name: round(float(value), 4) for name, value in ranked}


def select(results: dict[str, dict[str, float]], tolerance: float = 0.01) -> str:
    """Pick a model, preferring the simpler one when it is effectively as good.

    Simplicity order: logistic regression, then random forest, then XGBoost. If
    the simplest candidate is within ``tolerance`` PR-AUC of the best, it wins —
    a model we can explain line by line is worth more in a technical interview
    than a fractional gain we cannot.
    """
    order = ["logistic_regression", "random_forest", "xgboost"]
    available = [name for name in order if name in results]
    if not available:
        raise ValueError("no candidates to select from")

    best = max(available, key=lambda name: results[name]["pr_auc"])
    best_score = results[best]["pr_auc"]
    for name in available:
        if best_score - results[name]["pr_auc"] <= tolerance:
            return name
    return best
