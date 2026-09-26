"""Load the clothing sales history and turn it into weekly planning data.

Source: "Retail Store Inventory Forecasting Dataset". Its own page describes it
as **synthetic but realistic**, so what we measure here shows that the method
works; it is not a claim about real shoppers. `docs/data-sources.md` says the
same, and the application repeats it on screen next to any accuracy figure.

What it gives us that matters:

* 14,626 Clothing rows — 20 styles across 5 stores over two years.
* A discount column running from 0% to 20%. **Measured, it carries almost no
  signal**: the correlation between discount and units sold is 0.036, the
  log-log slope is -0.07, and average weekly units move from 1,003 at full price
  to 1,105 at the deepest discount — about 10%, and not monotonic in between.
  A real apparel markdown moves volume far more than that. The design assumed we
  could fit an elasticity from this column; we cannot, and `markdown` states the
  assumption it uses instead rather than dressing up a curve fitted to noise.
* Inventory levels, so safety stock can be checked against what actually
  happened rather than only against a formula.

**The file is not a daily series.** Each style-store pair has between 122 and 176
observations across 730 days, so a week typically holds one or two readings, not
seven. Summing a week would therefore say demand collapsed in the weeks that
happen to be sampled less — an artefact of the sampling, not of the business.

So weekly demand is a **rate**: observed units divided by observed days, times
seven, with the number of observations kept alongside so thin weeks are visible
rather than silently equal to full ones.

Planning happens at style and week across the network, because that is the grain
an S&OP cycle commits to. Store detail is kept separately for inventory and
distribution, where it is genuinely needed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pyshared.timeutil import to_week_start

CATEGORY = "Clothing"

WEEKLY_COLUMNS: set[str] = {
    "style_id", "store_id", "week_start", "week_index", "units", "price",
    "discount_pct", "promo_weeks", "inventory", "seasonality", "origin",
}


def load_daily(path: Path) -> pd.DataFrame:
    """The raw clothing rows, typed and renamed."""
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run: python scripts/fetch_data.py")

    raw = pd.read_csv(path)
    clothing = raw[raw["Category"] == CATEGORY].copy()

    df = pd.DataFrame({
        "date": pd.to_datetime(clothing["Date"], errors="coerce"),
        "style_id": clothing["Product ID"].astype(str),
        "store_id": clothing["Store ID"].astype(str),
        "region": clothing["Region"].astype("string").str.strip(),
        "units": pd.to_numeric(clothing["Units Sold"], errors="coerce").fillna(0).clip(lower=0),
        "inventory": pd.to_numeric(clothing["Inventory Level"], errors="coerce").fillna(0),
        "ordered": pd.to_numeric(clothing["Units Ordered"], errors="coerce").fillna(0),
        "price": pd.to_numeric(clothing["Price"], errors="coerce"),
        "discount_pct": pd.to_numeric(clothing["Discount"], errors="coerce").fillna(0) / 100.0,
        "promo": (
            pd.to_numeric(clothing["Holiday/Promotion"], errors="coerce").fillna(0).astype(int)
        ),
        "competitor_price": pd.to_numeric(clothing["Competitor Pricing"], errors="coerce"),
        "seasonality": clothing["Seasonality"].astype("string").str.strip(),
        "weather": clothing["Weather Condition"].astype("string").str.strip(),
    })

    return df.dropna(subset=["date", "price"]).sort_values(["date", "style_id", "store_id"])


def _weighted(values: pd.Series, weights: pd.Series) -> float:
    """Average weighted by units, falling back to a plain mean in a dead week."""
    total = weights.sum()
    return float((values * weights).sum() / total) if total > 0 else float(values.mean())


def _aggregate(daily: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Aggregate to a weekly rate over the given keys."""
    working = daily.copy()
    working["week_start"] = to_week_start(working["date"])
    group_keys = [*keys, "week_start"]

    base = working.groupby(group_keys, as_index=False).agg(
        observed_units=("units", "sum"),
        observations=("date", "nunique"),
        inventory=("inventory", "last"),
        ordered=("ordered", "sum"),
        promo_weeks=("promo", "max"),
    )

    weighted = (
        working.groupby(group_keys)
        .apply(
            lambda g: pd.Series({
                "price": _weighted(g["price"], g["units"]),
                "discount_pct": _weighted(g["discount_pct"], g["units"]),
                "competitor_price": _weighted(g["competitor_price"], g["units"]),
            }),
            include_groups=False,
        )
        .reset_index()
    )

    seasonality = (
        working.groupby(group_keys)["seasonality"]
        .agg(lambda s: s.value_counts().index[0])
        .reset_index()
    )

    weekly = base.merge(weighted, on=group_keys).merge(seasonality, on=group_keys)

    # Units as a weekly rate, because a week with two readings is not a week
    # with two days of trade.
    weekly["units"] = (weekly["observed_units"] / weekly["observations"] * 7).round(1)

    first_week = weekly["week_start"].min()
    weekly["week_index"] = ((weekly["week_start"] - first_week).dt.days // 7).astype(int)
    weekly["origin"] = "public-synthetic"

    return weekly.sort_values([*keys, "week_start"]).reset_index(drop=True)


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly demand per style across the network — the S&OP planning grain."""
    weekly = _aggregate(daily, ["style_id"])
    weekly["store_id"] = "network"

    missing = WEEKLY_COLUMNS - set(weekly.columns)
    if missing:
        raise ValueError(f"weekly sales is missing columns: {sorted(missing)}")
    return weekly


def to_weekly_by_store(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly demand per style and store, for inventory and distribution."""
    return _aggregate(daily, ["style_id", "store_id"])


def load_weekly_sales(path: Path) -> pd.DataFrame:
    return to_weekly(load_daily(path))


def load_weekly_store_sales(path: Path) -> pd.DataFrame:
    return to_weekly_by_store(load_daily(path))


def price_response(weekly: pd.DataFrame) -> pd.DataFrame:
    """Units sold at each discount level — the evidence behind markdown advice."""
    return (
        weekly.groupby(weekly["discount_pct"].round(2))
        .agg(weeks=("units", "size"), mean_units=("units", "mean"), mean_price=("price", "mean"))
        .reset_index()
        .rename(columns={"discount_pct": "discount"})
    )


def summarise(weekly: pd.DataFrame) -> dict[str, float | int | str]:
    return {
        "rows": int(len(weekly)),
        "styles": int(weekly["style_id"].nunique()),
        "median_observations_per_week": float(weekly["observations"].median()),
        "weeks": int(weekly["week_index"].nunique()),
        "first_week": str(weekly["week_start"].min().date()),
        "last_week": str(weekly["week_start"].max().date()),
        "total_units": float(weekly["units"].sum()),
        "median_weekly_units": float(weekly["units"].median()),
        "discount_levels": int(weekly["discount_pct"].round(2).nunique()),
        "weeks_on_promotion": round(float(weekly["promo_weeks"].mean()), 4),
        "mean_units_at_full_price": round(
            float(weekly.loc[weekly["discount_pct"] < 0.01, "units"].mean()), 2
        ),
        "mean_units_at_max_discount": round(
            float(weekly.loc[weekly["discount_pct"] >= 0.19, "units"].mean()), 2
        ),
    }


def seasonal_index(weekly: pd.DataFrame) -> pd.Series:
    """Week-of-year demand index, normalised to average 1.0."""
    by_week = weekly.groupby(weekly["week_start"].dt.isocalendar().week)["units"].mean()
    index = by_week / by_week.mean()
    return index.rolling(5, center=True, min_periods=1).mean().clip(0.7, 1.4)


def launch_curve(weekly: pd.DataFrame, weeks: int = 13) -> np.ndarray:
    """The shape of a style's first weeks on sale, used for cold-start forecasts."""
    first_weeks = weekly.groupby("style_id")["week_index"].transform("min")
    age = weekly["week_index"] - first_weeks
    early = weekly[age < weeks].assign(age=age[age < weeks])
    shape = early.groupby("age")["units"].mean()
    normalised = (shape / shape.mean()).reindex(range(weeks)).ffill().fillna(1.0)
    return normalised.to_numpy()
