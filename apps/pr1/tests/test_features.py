"""Point-in-time features for the risk models.

Every trailing feature must be computed from orders that came *before* the one
being scored. Get this wrong and the models look excellent in testing and fail in
production, because they were quietly told the answer. Most of these tests use
tiny hand-built fixtures where the correct value can be worked out on paper.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from supplyguard.config import RAW_SCMS
from supplyguard.etl.scms import load_scms
from supplyguard.features.build import FEATURE_COLUMNS, build_order_features


def _fixture(rows: list[tuple[str, str, int, float]]) -> pd.DataFrame:
    """(supplier, promised date, is_late, qty) -> a frame the builder accepts."""
    return pd.DataFrame({
        "po_id": [f"po-{i}" for i in range(len(rows))],
        "supplier_id": [r[0] for r in rows],
        "promised_date": pd.to_datetime([r[1] for r in rows]),
        "po_date": pd.to_datetime([r[1] for r in rows]) - pd.Timedelta(days=60),
        "delivered_date": pd.to_datetime([r[1] for r in rows]),
        "is_late": [r[2] for r in rows],
        "late_days": [5 * r[2] for r in rows],
        "qty": [r[3] for r in rows],
        "line_value": [r[3] * 2.0 for r in rows],
        "unit_price": [2.0] * len(rows),
        "weight_kg": [r[3] * 0.1 for r in rows],
        "freight_cost": [10.0] * len(rows),
        "freight_known": [True] * len(rows),
        "shipment_mode": ["Air"] * len(rows),
        "product_group": ["ARV"] * len(rows),
        "country": ["Nigeria"] * len(rows),
        "promised_lead_days": [60] * len(rows),
    })


def test_first_order_for_a_supplier_has_no_history() -> None:
    df = _fixture([("a", "2020-01-01", 1, 10.0)])
    out = build_order_features(df)
    assert pd.isna(out["supplier_prior_late_rate"].iloc[0])
    assert out["supplier_prior_orders"].iloc[0] == 0


def test_trailing_late_rate_uses_only_earlier_orders() -> None:
    df = _fixture([
        ("a", "2020-01-01", 1, 10.0),
        ("a", "2020-02-01", 0, 10.0),
        ("a", "2020-03-01", 1, 10.0),
    ])
    out = build_order_features(df).sort_values("promised_date")
    assert pd.isna(out["supplier_prior_late_rate"].iloc[0])      # nothing known yet
    assert out["supplier_prior_late_rate"].iloc[1] == 1.0        # order 1 only
    assert out["supplier_prior_late_rate"].iloc[2] == 0.5        # orders 1 and 2


def test_the_row_own_outcome_never_leaks_into_its_features() -> None:
    """The decisive test: flipping one row's label must not change its features."""
    rows = [("a", "2020-01-01", 0, 10.0), ("a", "2020-02-01", 0, 10.0)]
    base = build_order_features(_fixture(rows))

    flipped_rows = [("a", "2020-01-01", 0, 10.0), ("a", "2020-02-01", 1, 10.0)]
    flipped = build_order_features(_fixture(flipped_rows))

    trailing = [c for c in FEATURE_COLUMNS if c.startswith("supplier_prior")]
    pd.testing.assert_frame_equal(base[trailing], flipped[trailing])


def test_destination_history_is_also_point_in_time() -> None:
    """Destination carries real signal, so it needs the same leakage discipline."""
    df = _fixture([
        ("a", "2020-01-01", 1, 10.0),
        ("b", "2020-02-01", 0, 10.0),
        ("c", "2020-03-01", 1, 10.0),
    ])
    out = build_order_features(df).sort_values("promised_date")
    assert pd.isna(out["destination_prior_late_rate"].iloc[0])
    assert out["destination_prior_late_rate"].iloc[1] == 1.0     # first order only
    assert out["destination_prior_late_rate"].iloc[2] == 0.5     # first two


def test_no_rows_are_dropped() -> None:
    df = _fixture([("a", "2020-01-01", 1, 10.0), ("b", "2020-01-02", 0, 5.0)])
    assert len(build_order_features(df)) == 2


def test_suppliers_do_not_see_each_other_history() -> None:
    df = _fixture([
        ("a", "2020-01-01", 1, 10.0),
        ("b", "2020-02-01", 0, 10.0),
        ("a", "2020-03-01", 0, 10.0),
    ])
    out = build_order_features(df).sort_values("promised_date")
    assert out["supplier_prior_orders"].iloc[1] == 0             # b's first order
    assert out["supplier_prior_orders"].iloc[2] == 1             # a's second


def test_order_size_is_relative_to_the_supplier_own_past() -> None:
    df = _fixture([
        ("a", "2020-01-01", 0, 100.0),
        ("a", "2020-02-01", 0, 200.0),
    ])
    out = build_order_features(df).sort_values("promised_date")
    assert out["order_size_vs_supplier_median"].iloc[1] == pytest.approx(2.0)


def test_every_declared_feature_exists_and_is_numeric() -> None:
    orders = load_scms(RAW_SCMS)
    out = build_order_features(orders)
    assert set(out.columns) >= FEATURE_COLUMNS
    for column in FEATURE_COLUMNS:
        assert pd.api.types.is_numeric_dtype(out[column]), column


def test_features_on_real_data_are_finite_where_present() -> None:
    orders = load_scms(RAW_SCMS)
    out = build_order_features(orders)
    for column in FEATURE_COLUMNS:
        values = out[column].dropna()
        assert np.isfinite(values).all(), f"{column} holds infinities"


def test_trailing_coverage_is_reported_honestly() -> None:
    """Early orders genuinely have no history; we expect a known share of gaps."""
    orders = load_scms(RAW_SCMS)
    out = build_order_features(orders)
    known = out["supplier_prior_late_rate"].notna().mean()
    assert 0.7 < known < 1.0


def test_build_is_deterministic() -> None:
    orders = load_scms(RAW_SCMS)
    pd.testing.assert_frame_equal(build_order_features(orders), build_order_features(orders))
