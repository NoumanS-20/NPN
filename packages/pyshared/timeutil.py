"""Time-aware splitting.

Both applications train on the past and test on the future. A random split would
let a model learn from records dated after the ones it is scored on, which
inflates every metric we report. These helpers make the chronological split the
easy path.
"""

from __future__ import annotations

import pandas as pd


def time_split(
    df: pd.DataFrame,
    date_col: str,
    test_fraction: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split ``df`` chronologically, oldest rows for training.

    Both sides always receive at least one row, so small fixtures in tests do not
    produce an empty frame.
    """
    if date_col not in df.columns:
        raise KeyError(f"{date_col!r} is not a column of the frame")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must sit between 0 and 1")
    if len(df) < 2:
        raise ValueError("need at least two rows to split")

    ordered = df.sort_values(date_col, kind="mergesort").reset_index(drop=True)
    cut = int(round(len(ordered) * (1 - test_fraction)))
    cut = min(max(cut, 1), len(ordered) - 1)
    return ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()


def split_boundaries(train: pd.DataFrame, test: pd.DataFrame, date_col: str) -> dict[str, str]:
    """The dates either side of a split, recorded with every model's metrics."""
    return {
        "train_start_date": str(train[date_col].min()),
        "train_end_date": str(train[date_col].max()),
        "test_start_date": str(test[date_col].min()),
        "test_end_date": str(test[date_col].max()),
    }


def to_week_start(series: pd.Series) -> pd.Series:
    """Snap timestamps to the Monday of their week, the planning grain both apps use."""
    dates = pd.to_datetime(series, errors="coerce")
    return dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")
