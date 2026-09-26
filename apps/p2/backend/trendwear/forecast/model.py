"""Weekly demand forecast per style.

LightGBM over lag, rolling, price, discount and seasonal features, trained on the
earlier weeks and tested on the later ones. Never a random split: a random split
lets the model see a style's future while predicting its past, which is the
fastest way to publish an accuracy figure that will not survive contact with
reality.

Three baselines, because a forecast is only as good as what it beats:

* **seasonal naive** — the same week last year, or the last observed week where
  there is no year of history. This is what a planner does without a model.
* **moving average** — the mean of the last four weeks.
* **the dataset's own forecast column** — the file ships a `Demand Forecast`
  field, and beating it is a fair external bar.

Accuracy is reported on the **real styles only**. Generated styles make the
catalogue realistic; they must not make the score look better.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from pyshared.metrics import regression_report_dict

from trendwear.config import SEED

LABEL = "units"
DATE_COLUMN = "week_start"

FEATURES = [
    "lag_1", "lag_2", "lag_4", "lag_52",
    "rolling_4", "rolling_13", "rolling_std_4",
    "price", "discount_pct", "price_vs_competitor",
    "promo_weeks", "week_of_year", "age_weeks",
]


@dataclass
class ForecastModel:
    estimator: Any
    features: list[str]
    metrics: dict[str, float | str]
    feature_importance: dict[str, float] = field(default_factory=dict)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = frame.reindex(columns=self.features).astype(float)
        return np.clip(self.estimator.predict(matrix), 0, None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> ForecastModel:
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing. Run: python -m trendwear.pipeline")
        return joblib.load(path)


def build_features(weekly: pd.DataFrame) -> pd.DataFrame:
    """Lags and rolling windows, computed per style and strictly backwards.

    Every feature uses `shift(1)` first, so a week's own sales never contribute
    to predicting it.
    """
    df = weekly.sort_values(["style_id", "week_index"]).copy()
    grouped = df.groupby("style_id", sort=False)["units"]

    df["lag_1"] = grouped.shift(1)
    df["lag_2"] = grouped.shift(2)
    df["lag_4"] = grouped.shift(4)
    df["lag_52"] = grouped.shift(52)
    df["rolling_4"] = grouped.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
    df["rolling_13"] = grouped.transform(lambda s: s.shift(1).rolling(13, min_periods=1).mean())
    df["rolling_std_4"] = grouped.transform(lambda s: s.shift(1).rolling(4, min_periods=2).std())

    df["week_of_year"] = df["week_start"].dt.isocalendar().week.astype(float)
    df["price_vs_competitor"] = df["price"] / df["competitor_price"].replace(0, np.nan)
    df["age_weeks"] = df["week_index"] - df.groupby("style_id")["week_index"].transform("min")

    return df


def _baselines(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, float]:
    """What the model has to beat."""
    scores: dict[str, float] = {}

    seasonal = test["lag_52"].fillna(test["lag_1"]).fillna(train["units"].mean())
    scores["wape_seasonal_naive"] = regression_report_dict(test[LABEL], seasonal)["wape"]

    moving = test["rolling_4"].fillna(train["units"].mean())
    scores["wape_moving_average"] = regression_report_dict(test[LABEL], moving)["wape"]

    if "dataset_forecast" in test and test["dataset_forecast"].notna().any():
        column = test["dataset_forecast"].fillna(test[LABEL].mean())
        scores["wape_dataset_column"] = regression_report_dict(test[LABEL], column)["wape"]

    return scores


def train(weekly: pd.DataFrame, test_fraction: float = 0.25) -> ForecastModel:
    """Fit on the earlier weeks, score on the later ones."""
    featured = build_features(weekly)

    # Rows with no history at all cannot be predicted from lags; they are what
    # the cold-start method exists for.
    usable = featured[featured["lag_1"].notna()].copy()

    cut_week = usable["week_index"].quantile(1 - test_fraction)
    train_df = usable[usable["week_index"] <= cut_week]
    test_df = usable[usable["week_index"] > cut_week]

    if len(test_df) == 0 or len(train_df) == 0:
        raise ValueError("the chronological split leaves one side empty")

    estimator = LGBMRegressor(
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=SEED,
        verbose=-1,
    )
    estimator.fit(train_df[FEATURES].astype(float), train_df[LABEL])

    # Reported on real styles only: generated rows make the catalogue realistic,
    # they must not make the score look better.
    real_test = test_df[test_df["origin"] != "synthetic"]
    scored = real_test if len(real_test) else test_df

    predictions = np.clip(estimator.predict(scored[FEATURES].astype(float)), 0, None)
    metrics: dict[str, float | str] = dict(regression_report_dict(scored[LABEL], predictions))
    metrics.update(_baselines(train_df, scored))

    metrics["train_rows"] = int(len(train_df))
    metrics["test_rows"] = int(len(scored))
    metrics["scored_on"] = "real styles only" if len(real_test) else "all styles"
    metrics["train_end_week"] = str(train_df["week_start"].max().date())
    metrics["test_start_week"] = str(scored["week_start"].min().date())
    metrics["beats_seasonal_naive"] = bool(metrics["wape"] < metrics["wape_seasonal_naive"])

    importance = dict(
        sorted(
            zip(FEATURES, estimator.feature_importances_.astype(float), strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    total = sum(importance.values()) or 1.0

    return ForecastModel(
        estimator=estimator,
        features=FEATURES,
        metrics=metrics,
        feature_importance={k: round(v / total, 4) for k, v in importance.items()},
    )


def forecast_horizon(
    model: ForecastModel,
    weekly: pd.DataFrame,
    style_id: str,
    horizon: int = 13,
) -> pd.DataFrame:
    """Forecast a style forward, feeding each prediction back as the next lag.

    Recursive rather than direct, because a planner needs a contiguous thirteen
    weeks and the later weeks have no actuals to lag from. The cost is that an
    early error propagates, which is honest: that is what happens in practice.
    """
    history = weekly[weekly["style_id"] == style_id].sort_values("week_index").copy()
    if history.empty:
        raise KeyError(f"no history for style {style_id!r}")

    rows = []
    working = history.copy()

    for step in range(1, horizon + 1):
        last = working.iloc[-1]
        next_week = int(last["week_index"]) + 1
        next_start = last["week_start"] + pd.Timedelta(weeks=1)

        # Build the next row as a one-row frame rather than a Series: appending a
        # Series collapses the column dtypes and week_start stops being a date.
        candidate = working.iloc[[-1]].copy()
        candidate["week_index"] = next_week
        candidate["week_start"] = next_start
        candidate["units"] = np.nan

        extended = pd.concat([working, candidate], ignore_index=True)
        extended["week_start"] = pd.to_datetime(extended["week_start"])
        featured = build_features(extended).iloc[[-1]]

        prediction = float(model.predict(featured)[0])
        rows.append({
            "style_id": style_id,
            "week_index": next_week,
            "week_start": next_start,
            "forecast_units": round(prediction, 1),
            "step": step,
        })

        extended.loc[extended.index[-1], "units"] = prediction
        working = extended

    return pd.DataFrame(rows)


def summarise(model: ForecastModel) -> dict[str, float | str]:
    metrics = model.metrics
    return {
        "wape": round(float(metrics["wape"]), 4),
        "mape": round(float(metrics["mape"]), 4),
        "bias": round(float(metrics["bias"]), 4),
        "wape_seasonal_naive": round(float(metrics["wape_seasonal_naive"]), 4),
        "wape_moving_average": round(float(metrics["wape_moving_average"]), 4),
        "beats_seasonal_naive": metrics["beats_seasonal_naive"],
        "scored_on": metrics["scored_on"],
        "test_rows": metrics["test_rows"],
    }
