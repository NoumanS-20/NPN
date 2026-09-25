"""Predict whether an order will be delivered after its promised date.

This is the model the use case names: *predict potential delivery delays before
PO release*. Its output does not sit in a report beside the plan — it enters the
allocation objective, so a supplier with a high probability of being late costs
more in the optimiser and receives less volume.

Data: SCMS delivery history, 10,324 real purchase orders, 11.5% late. Trained on
the earlier orders and tested on the later ones, because a random split would let
the model learn from the future.

Three candidates are trained on identical features and the identical split —
logistic regression, random forest and XGBoost — and the winner is kept. Where
the simpler model is within 0.01 PR-AUC we keep the simpler one: being able to
explain the model line by line is worth more than a fractional gain.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from supplyguard.config import SEED
from supplyguard.features.build import FEATURE_COLUMNS
from supplyguard.risk.base import (
    TrainedModel,
    chronological_split,
    evaluate,
    fit_calibrated,
    importance_from,
    select,
)

LABEL = "is_late"
DATE_COLUMN = "promised_date"
PRIOR_COLUMN = "supplier_prior_late_rate"

FEATURES = sorted(FEATURE_COLUMNS)


def _candidates(positive_weight: float) -> dict[str, object]:
    """The three models we compare, each with the same job to do."""
    return {
        # Median imputation and scaling are needed only by the linear model;
        # the tree models take missing values natively, which matters because
        # "no history with this supplier" is information, not a gap to fill.
        "logistic_regression": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
        "random_forest": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=SEED,
                n_jobs=-1,
            )),
        ]),
        "xgboost": XGBClassifier(
            n_estimators=400,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            scale_pos_weight=positive_weight,
            eval_metric="aucpr",
            random_state=SEED,
            n_jobs=-1,
        ),
    }


def _real_only(df: pd.DataFrame) -> pd.DataFrame:
    """Every reported number is measured on real records."""
    return df[df["origin"] == "real"] if "origin" in df else df


def benchmark(features: pd.DataFrame, test_fraction: float = 0.25) -> dict[str, dict[str, float]]:
    """Train all three candidates on the same split and score them identically."""
    data = _real_only(features)
    train_df, test_df = chronological_split(data, DATE_COLUMN, LABEL, test_fraction)

    positives = max(int(train_df[LABEL].sum()), 1)
    weight = float((len(train_df) - positives) / positives)

    results: dict[str, dict[str, float]] = {}
    for name, estimator in _candidates(weight).items():
        fitted = fit_calibrated(estimator, train_df, FEATURES, LABEL, DATE_COLUMN)
        results[name] = evaluate(
            fitted, train_df, test_df, FEATURES, LABEL, DATE_COLUMN, PRIOR_COLUMN
        )
    return results


def train(features: pd.DataFrame, test_fraction: float = 0.25) -> TrainedModel:
    """Benchmark the candidates, keep the winner, return it fitted and scored."""
    data = _real_only(features)
    train_df, test_df = chronological_split(data, DATE_COLUMN, LABEL, test_fraction)

    positives = max(int(train_df[LABEL].sum()), 1)
    weight = float((len(train_df) - positives) / positives)

    fitted: dict[str, object] = {}
    results: dict[str, dict[str, float]] = {}
    for name, estimator in _candidates(weight).items():
        model = fit_calibrated(estimator, train_df, FEATURES, LABEL, DATE_COLUMN)
        fitted[name] = model
        results[name] = evaluate(
            model, train_df, test_df, FEATURES, LABEL, DATE_COLUMN, PRIOR_COLUMN
        )

    chosen = select(results)
    estimator = fitted[chosen]

    metrics = dict(results[chosen])
    metrics["model"] = chosen
    metrics["label"] = LABEL

    return TrainedModel(
        name="delay",
        estimator=estimator,
        features=FEATURES,
        metrics=metrics,
        feature_importance=importance_from(estimator, FEATURES),
        candidates={name: {k: v for k, v in m.items() if isinstance(v, float)}
                    for name, m in results.items()},
    )


def comparison_table(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """The benchmark, formatted for the model panel and the module guide."""
    rows = [
        {
            "model": name,
            "precision": round(metrics["precision"], 3),
            "recall": round(metrics["recall"], 3),
            "f1": round(metrics["f1"], 3),
            "roc_auc": round(metrics["roc_auc"], 3),
            "pr_auc": round(metrics["pr_auc"], 3),
        }
        for name, metrics in results.items()
    ]
    return pd.DataFrame(rows).sort_values("pr_auc", ascending=False).reset_index(drop=True)


def score_orders(model: TrainedModel, features: pd.DataFrame) -> np.ndarray:
    """Probability of lateness for each order, used by the optimiser and the API."""
    return model.predict_proba(features)
