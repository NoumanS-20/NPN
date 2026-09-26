"""SCMS delivery history is PR1's primary dataset and the only tier-1 source
behind our headline risk metrics, so its load is pinned hard by these tests.

The numbers asserted here were measured from the file on 25 September 2026.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pyshared.currency import USD_TO_INR
from supplyguard.config import RAW_SCMS
from supplyguard.etl.scms import REQUIRED_COLUMNS, load_scms


@pytest.fixture(scope="module")
def scms() -> pd.DataFrame:
    return load_scms(RAW_SCMS)


def test_every_row_loads(scms: pd.DataFrame) -> None:
    assert len(scms) == 10_324


def test_contract_columns_are_present(scms: pd.DataFrame) -> None:
    assert set(scms.columns) >= REQUIRED_COLUMNS


def test_supplier_entity_is_vendor_plus_site(scms: pd.DataFrame) -> None:
    assert scms["supplier_id"].nunique() == 217
    assert scms["vendor"].nunique() == 73
    assert scms["site"].nunique() == 88
    assert scms["supplier_id"].isna().sum() == 0


def test_delivery_labels_match_the_measured_rate(scms: pd.DataFrame) -> None:
    assert scms["late_days"].notna().all()
    assert 0.10 < scms["is_late"].mean() < 0.13          # measured: 11.5%
    assert scms["is_late"].isin([0, 1]).all()


def test_no_negative_quantities_or_prices(scms: pd.DataFrame) -> None:
    assert (scms["qty"] >= 0).all()
    assert (scms["unit_price"] >= 0).all()
    assert (scms["line_value"] >= 0).all()


def test_promised_date_follows_the_order_date_for_most_rows(scms: pd.DataFrame) -> None:
    known = scms["po_date"].notna()
    ordered = scms.loc[known, "promised_date"] >= scms.loc[known, "po_date"]
    assert ordered.mean() > 0.85


def test_placeholder_dates_become_missing_not_epoch(scms: pd.DataFrame) -> None:
    """The file uses 'Date Not Captured' and 'Pre-PO Process' as date values."""
    assert scms["po_date"].isna().any()
    assert scms["po_date"].min() > pd.Timestamp("2000-01-01")


def test_freight_cost_is_numeric_with_bundled_and_known_flags(scms: pd.DataFrame) -> None:
    """40% of rows carry text instead of a number, in three different senses."""
    assert pd.api.types.is_float_dtype(scms["freight_cost"])
    assert scms["freight_bundled"].dtype == bool
    assert scms["freight_known"].dtype == bool
    assert scms["freight_bundled"].any()
    assert (scms.loc[scms["freight_bundled"], "freight_cost"] == 0).all()
    assert (scms.loc[~scms["freight_known"], "freight_cost"] == 0).all()
    assert 0.55 < scms["freight_known"].mean() < 0.65          # measured: 60% are real numbers


def test_cross_reference_text_never_becomes_a_freight_amount(scms: pd.DataFrame) -> None:
    """Regression: 'See DN-93 (ID#:1281)' must not parse as 931281.

    Stripping non-digits from that string produced a 931,281 freight charge on
    2,445 rows, which would have silently corrupted every cost comparison.

    The ceiling below is written in dollars and converted, because the source
    column is dollars and the sane-maximum judgement was made about dollars. Had
    it been hardcoded in rupees it would have had to be re-reasoned from scratch
    the next time the rate changed.
    """
    raw = pd.read_csv(RAW_SCMS, low_memory=False)
    reference_rows = raw["Freight Cost (USD)"].astype(str).str.contains("See ", na=False)
    assert reference_rows.sum() > 2000                          # the rows exist
    ids = set(raw.loc[reference_rows, "ID"].astype(str))
    affected = scms[scms["po_id"].isin(ids)]
    assert (affected["freight_cost"] == 0).all()
    assert not affected["freight_known"].any()
    # No absurd charges anywhere: 300k dollars is already far above any real
    # freight line in this data, and the column is now stored in rupees.
    assert scms["freight_cost"].max() < 300_000 * USD_TO_INR


def test_every_row_is_marked_as_real(scms: pd.DataFrame) -> None:
    assert set(scms["origin"].unique()) == {"real"}


def test_competition_exists_within_a_product_group(scms: pd.DataFrame) -> None:
    """The allocation problem is only meaningful if suppliers compete."""
    per_group = scms.groupby("product_group")["supplier_id"].nunique()
    assert per_group.max() >= 100


def test_load_is_deterministic(scms: pd.DataFrame) -> None:
    again = load_scms(RAW_SCMS)
    pd.testing.assert_frame_equal(scms, again)
