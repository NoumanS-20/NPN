"""Train a risk model on a small label — and refuse to ship it if it is not real.

The delay model has 10,324 orders behind it. Quality has 517 and disruption 777,
and one of the two files is openly synthetic. A model trained on that much data
can easily score well enough to look convincing while having learned nothing, and
the panel on 30 September will ask.

So these models pass through a **sufficiency gate**. A label supports a model only
when, on the held-out later period, the model beats both baselines by a margin
that is not noise. If it does not, we say so, and the estimator falls back to the
supplier's own observed rate — which is honest, still useful to the optimiser, and
far easier to defend than a model we do not believe.

The gate is deliberately strict, because the failure it prevents (a confident
number with nothing behind it) is much worse than the failure it causes (a
simpler, plainly labelled fallback).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from supplyguard.config import SEED
from supplyguard.risk.base import (
    TrainedModel,
    chronological_split,
    evaluate,
    fit_calibrated,
    importance_from,
    select,
)

# A model must clear the better of its two baselines by this much PR-AUC, and
# rank better than a coin toss, before we call the label sufficient.
MIN_PR_AUC_GAIN = 0.03
MIN_ROC_AUC = 0.58


@dataclass
class EmpiricalRate:
    """Fallback estimator: this supplier's observed rate, else the overall rate.

    Not a placeholder — it is what a procurement team already does, and it is a
    perfectly reasonable input to the optimiser. It simply makes no claim to be
    a prediction.
    """

    rates: dict[str, float]
    overall: float
    key: str = "supplier_id"
    needs_raw_frame: bool = True

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        mapped = df[self.key].map(self.rates).fillna(self.overall).to_numpy(dtype=float)
        return np.column_stack([1 - mapped, mapped])


def _candidates(positive_weight: float) -> dict[str, object]:
    """Only the two simpler models. 517 rows cannot support a boosted ensemble."""
    return {
        "logistic_regression": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
        "random_forest": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=10,
                class_weight="balanced",
                random_state=SEED,
                n_jobs=-1,
            )),
        ]),
    }


def _is_sufficient(metrics: dict[str, float | str]) -> tuple[bool, str]:
    """Did the label support a model, on the evidence?"""
    pr_auc = float(metrics["pr_auc"])
    roc_auc = float(metrics["roc_auc"])
    baselines = [
        float(metrics.get("baseline_prior_pr_auc", 0.0)),
        float(metrics.get("baseline_majority_pr_auc", 0.0)),
    ]
    best_baseline = max(baselines)
    gain = pr_auc - best_baseline

    if roc_auc < MIN_ROC_AUC:
        return False, (
            f"ROC-AUC {roc_auc:.3f} is below {MIN_ROC_AUC}: the model barely ranks "
            "orders better than chance."
        )
    if gain < MIN_PR_AUC_GAIN:
        return False, (
            f"PR-AUC {pr_auc:.3f} beats the best baseline ({best_baseline:.3f}) by only "
            f"{gain:.3f}, under the {MIN_PR_AUC_GAIN} we require to call the gain real."
        )
    return True, (
        f"PR-AUC {pr_auc:.3f} beats the best baseline ({best_baseline:.3f}) by {gain:.3f} "
        f"with ROC-AUC {roc_auc:.3f}."
    )


def train_small_label(
    df: pd.DataFrame,
    *,
    name: str,
    label: str,
    date_column: str,
    features: list[str],
    prior_column: str,
    test_fraction: float = 0.3,
) -> TrainedModel:
    """Benchmark, judge, and return either a model or an honest fallback."""
    train_df, test_df = chronological_split(df, date_column, label, test_fraction)

    positives = max(int(train_df[label].sum()), 1)
    weight = float((len(train_df) - positives) / positives)

    fitted: dict[str, object] = {}
    results: dict[str, dict[str, float]] = {}
    for candidate, estimator in _candidates(weight).items():
        model = fit_calibrated(estimator, train_df, features, label, date_column)
        fitted[candidate] = model
        results[candidate] = evaluate(
            model, train_df, test_df, features, label, date_column, prior_column
        )

    chosen = select(results)
    metrics = dict(results[chosen])
    sufficient, reason = _is_sufficient(metrics)

    metrics["model"] = chosen if sufficient else "supplier_observed_rate"
    metrics["label"] = label
    metrics["label_sufficient"] = sufficient
    metrics["sufficiency_reason"] = reason
    metrics["rows"] = int(len(df))
    metrics["positives"] = int(df[label].sum())

    if sufficient:
        estimator = fitted[chosen]
        importance = importance_from(estimator, features)
    else:
        metrics["fallback"] = "supplier_observed_rate"
        rates = train_df.groupby("supplier_id")[label].mean().to_dict()
        estimator = EmpiricalRate(rates=rates, overall=float(train_df[label].mean()))
        importance = {}

    return TrainedModel(
        name=name,
        estimator=estimator,
        features=features,
        metrics=metrics,
        feature_importance=importance,
        candidates={
            candidate: {k: v for k, v in scores.items() if isinstance(v, float)}
            for candidate, scores in results.items()
        },
    )
