"""Forecast a style that has never been sold.

TrendWear launches a new line every six weeks, so the styles that matter most
commercially are exactly the ones with no history. A lag-based model has nothing
to work with, and this is the module that fills the gap.

**Analog similarity is the method we ship.** A new style is forecast as a
weighted blend of comparable styles — same category, nearest price band, same
season — scaled by how a launch typically ramps. Every step can be read off the
screen and defended in an interview: *these five styles are similar, here is how
they sold, here is the average, shaped by the usual launch curve.*

Chronos-Bolt, an open Hugging Face forecasting model, is run as a **benchmark
only**, and only when it is available locally. It answers "did you try a modern
foundation model?" with a measured number instead of an opinion. It never ships
in the plan: it needs a download the demo laptop may not have, and a method a
buyer cannot inspect is a poor basis for a production commitment.

Both are scored the same way: hold a real style out entirely, forecast it from
nothing, and compare against what it actually sold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyshared.metrics import regression_report_dict

from trendwear.config import SEED

DEFAULT_ANALOGS = 5


def find_analogs(
    style: pd.Series,
    catalogue: pd.DataFrame,
    weekly: pd.DataFrame,
    count: int = DEFAULT_ANALOGS,
) -> pd.DataFrame:
    """The most comparable styles that already have history.

    Comparability is category first, then price, then season — the order a
    merchandiser would use. Returned with the weight each analog carries, so the
    screen can show its working.
    """
    with_history = set(weekly["style_id"].unique())
    pool = catalogue[
        (catalogue["style_id"] != style["style_id"])
        & (catalogue["style_id"].isin(with_history))
    ].copy()

    if pool.empty:
        return pool.assign(weight=[])

    price_spread = max(float(pool["price"].std()), 1.0)
    pool["price_distance"] = (pool["price"] - style["price"]).abs() / price_spread
    pool["same_category"] = (pool["category"] == style["category"]).astype(int)
    pool["same_season"] = (pool["season"] == style["season"]).astype(int)

    # Lower is closer. Category dominates, price separates within it, season is
    # a tiebreak.
    pool["distance"] = (
        (1 - pool["same_category"]) * 2.0
        + pool["price_distance"]
        + (1 - pool["same_season"]) * 0.5
    )

    nearest = pool.nsmallest(count, "distance").copy()
    nearest["weight"] = 1 / (1 + nearest["distance"])
    nearest["weight"] = nearest["weight"] / nearest["weight"].sum()
    return nearest[["style_id", "name", "category", "season", "price", "distance", "weight"]]


def forecast_new_style(
    style: pd.Series,
    catalogue: pd.DataFrame,
    weekly: pd.DataFrame,
    launch_shape: np.ndarray,
    horizon: int = 13,
    count: int = DEFAULT_ANALOGS,
) -> pd.DataFrame:
    """Weighted blend of the analogs' launch weeks, scaled to this style's price.

    Scaling by price is deliberate: a £90 jacket does not sell the volume of a
    £20 tee, and a blend that ignored that would over-forecast every premium
    launch.
    """
    analogs = find_analogs(style, catalogue, weekly, count)
    if analogs.empty:
        level = float(weekly["units"].median())
        return pd.DataFrame({
            "week": range(1, horizon + 1),
            "forecast_units": [round(level * shape, 1) for shape in launch_shape[:horizon]],
            "method": "analog",
            "analogs": 0,
        })

    levels = weekly.groupby("style_id")["units"].mean()
    prices = catalogue.set_index("style_id")["price"]

    blended = 0.0
    for analog in analogs.itertuples():
        analog_price = float(prices.get(analog.style_id, style["price"]))
        # Cheaper styles sell more units; scale the analog's level by the price
        # ratio, bounded so one odd price point cannot dominate.
        price_ratio = np.clip(analog_price / max(float(style["price"]), 1.0), 0.4, 2.5)
        blended += analog.weight * float(levels.get(analog.style_id, 0.0)) * price_ratio

    shape = launch_shape[:horizon]
    if len(shape) < horizon:
        shape = np.pad(shape, (0, horizon - len(shape)), mode="edge")

    return pd.DataFrame({
        "week": range(1, horizon + 1),
        "forecast_units": np.round(blended * shape, 1),
        "method": "analog",
        "analogs": len(analogs),
    })


def forecast_with_chronos(
    style: pd.Series,
    catalogue: pd.DataFrame,
    weekly: pd.DataFrame,
    horizon: int = 13,
    count: int = DEFAULT_ANALOGS,
) -> pd.DataFrame | None:
    """Benchmark only: an open Hugging Face model on the analogs' mean series.

    Returns ``None`` when the model is not installed or cannot be loaded, which
    is the expected case on a machine without the download. The caller records
    that and carries on — the benchmark is never allowed to break a plan.
    """
    try:
        import torch
        from chronos import ChronosPipeline
    except Exception:
        return None

    analogs = find_analogs(style, catalogue, weekly, count)
    if analogs.empty:
        return None

    series = (
        weekly[weekly["style_id"].isin(analogs["style_id"])]
        .groupby("week_index")["units"]
        .mean()
        .to_numpy()
    )
    if len(series) < 8:
        return None

    try:
        pipeline = ChronosPipeline.from_pretrained("amazon/chronos-bolt-small")
        forecast = pipeline.predict(torch.tensor(series, dtype=torch.float32), horizon)
        median = np.median(forecast[0].numpy(), axis=0)
    except Exception:
        return None

    return pd.DataFrame({
        "week": range(1, horizon + 1),
        "forecast_units": np.round(np.clip(median, 0, None), 1),
        "method": "chronos",
        "analogs": len(analogs),
    })


def category_average(style: pd.Series, catalogue: pd.DataFrame, weekly: pd.DataFrame,
                     horizon: int = 13) -> pd.DataFrame:
    """The simplest defensible baseline: what this category sells on average."""
    same = catalogue[catalogue["category"] == style["category"]]["style_id"]
    level = float(weekly[weekly["style_id"].isin(same)]["units"].mean())
    if not np.isfinite(level):
        level = float(weekly["units"].mean())

    return pd.DataFrame({
        "week": range(1, horizon + 1),
        "forecast_units": np.round([level] * horizon, 1),
        "method": "category_average",
        "analogs": 0,
    })


def evaluate_holdout(
    catalogue: pd.DataFrame,
    weekly: pd.DataFrame,
    launch_shape: np.ndarray,
    horizon: int = 13,
    seed: int = SEED,
) -> dict[str, object]:
    """Hide a real style, forecast it from nothing, score every method.

    This is what makes the cold-start claim measurable rather than asserted. The
    held-out style is removed from the history the methods may use, so nothing
    can leak back in.
    """
    rng = np.random.default_rng(seed)

    real = catalogue[catalogue["origin"] == "real"]
    candidates = [
        style_id
        for style_id in real["style_id"]
        if (weekly["style_id"] == style_id).sum() >= horizon
    ]
    if not candidates:
        return {"scored": False, "reason": "no real style has enough history to hold out"}

    held_out = str(rng.choice(candidates))
    style = real[real["style_id"] == held_out].iloc[0]

    actual = (
        weekly[weekly["style_id"] == held_out]
        .sort_values("week_index")["units"]
        .to_numpy()[:horizon]
    )
    visible = weekly[weekly["style_id"] != held_out]

    results: dict[str, dict[str, float]] = {}

    analog = forecast_new_style(style, catalogue, visible, launch_shape, horizon)
    results["analog"] = regression_report_dict(actual, analog["forecast_units"].to_numpy())

    baseline = category_average(style, catalogue, visible, horizon)
    results["category_average"] = regression_report_dict(
        actual, baseline["forecast_units"].to_numpy()
    )

    chronos = forecast_with_chronos(style, catalogue, visible, horizon)
    if chronos is not None:
        results["chronos"] = regression_report_dict(
            actual, chronos["forecast_units"].to_numpy()
        )
        chronos_note = "scored"
    else:
        chronos_note = "not installed on this machine; the analog method is unaffected"

    best = min(results, key=lambda name: results[name]["wape"])
    return {
        "scored": True,
        "held_out_style": held_out,
        "held_out_name": str(style["name"]),
        "horizon": horizon,
        "results": {
            name: {k: round(v, 4) for k, v in score.items()}
            for name, score in results.items()
        },
        "best_method": best,
        "chronos": chronos_note,
        "analog_beats_baseline": results["analog"]["wape"] < results["category_average"]["wape"],
    }
