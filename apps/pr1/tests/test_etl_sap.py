"""The SAP tables are Google Cloud's public demonstration data.

The table structures are genuine SAP (LFA1, EKKO, EKPO, EKET, EKBE); the contents
are simulated. We use them for the wider supplier catalogue and to show that we
can read ERP-shaped data, never as evidence of real supplier behaviour. These
tests pin both the numbers and that labelling.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_SAP_DIR
from supplyguard.etl.sap import load_po_outcomes, load_vendor_master


@pytest.fixture(scope="module")
def vendors() -> pd.DataFrame:
    return load_vendor_master(RAW_SAP_DIR)


@pytest.fixture(scope="module")
def outcomes() -> pd.DataFrame:
    return load_po_outcomes(RAW_SAP_DIR)


def test_vendor_master_row_count(vendors: pd.DataFrame) -> None:
    assert vendors["supplier_id"].nunique() == 2590
    assert len(vendors) == vendors["supplier_id"].nunique()      # one row per vendor


def test_vendor_master_spans_many_countries(vendors: pd.DataFrame) -> None:
    assert vendors["country"].nunique() > 30


def test_vendor_master_is_labelled_public_synthetic(vendors: pd.DataFrame) -> None:
    assert set(vendors["origin"].unique()) == {"public-synthetic"}
    assert set(vendors["source"].unique()) == {"sap"}


def test_vendor_names_are_populated(vendors: pd.DataFrame) -> None:
    assert vendors["name"].notna().all()
    assert (vendors["name"].str.len() > 0).all()


def test_po_outcomes_join_schedule_lines_to_goods_receipts(outcomes: pd.DataFrame) -> None:
    assert len(outcomes) > 150_000
    assert outcomes["promised_date"].notna().all()
    assert outcomes["received_date"].notna().all()


def test_po_outcome_late_rate_matches_the_measured_value(outcomes: pd.DataFrame) -> None:
    assert 0.43 < outcomes["is_late"].mean() < 0.48             # measured: 45.4%
    assert outcomes["is_late"].isin([0, 1]).all()


def test_po_outcomes_carry_a_vendor(outcomes: pd.DataFrame) -> None:
    assert outcomes["supplier_id"].notna().all()


def test_transactional_coverage_is_narrow_and_we_know_it(outcomes: pd.DataFrame) -> None:
    """The master holds 2,590 vendors but only 25 of them ever transact here.

    That gap is the whole reason the catalogue marks suppliers without history
    as unknown rather than assuming they behave like the average.
    """
    assert outcomes["supplier_id"].nunique() < 50


def test_po_outcomes_are_labelled_public_synthetic(outcomes: pd.DataFrame) -> None:
    assert set(outcomes["origin"].unique()) == {"public-synthetic"}


def test_late_days_are_consistent_with_the_two_dates(outcomes: pd.DataFrame) -> None:
    recomputed = (outcomes["received_date"] - outcomes["promised_date"]).dt.days
    assert (recomputed == outcomes["late_days"]).all()
