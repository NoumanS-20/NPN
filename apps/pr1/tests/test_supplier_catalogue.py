"""The supplier catalogue is what the buyer compares and what the optimiser
chooses from. One row per supplier entity, with the performance statistics that
drive both the comparison screen and the allocation objective.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_SAP_DIR, RAW_SCMS
from supplyguard.etl.scms import load_scms
from supplyguard.etl.suppliers import CATALOGUE_COLUMNS, build_catalogue


@pytest.fixture(scope="module")
def catalogue() -> pd.DataFrame:
    return build_catalogue(load_scms(RAW_SCMS), sap_dir=RAW_SAP_DIR)


def test_one_row_per_supplier_entity(catalogue: pd.DataFrame) -> None:
    assert catalogue["supplier_id"].is_unique


def test_contract_columns_are_present(catalogue: pd.DataFrame) -> None:
    assert set(catalogue.columns) >= CATALOGUE_COLUMNS


def test_the_trading_suppliers_are_all_present(catalogue: pd.DataFrame) -> None:
    traded = catalogue[catalogue["source"] == "scms"]
    assert len(traded) == 217
    assert set(traded["origin"].unique()) == {"real"}


def test_the_sap_catalogue_adds_the_wider_vendor_list(catalogue: pd.DataFrame) -> None:
    from_sap = catalogue[catalogue["source"] == "sap"]
    assert len(from_sap) > 2000
    assert set(from_sap["origin"].unique()) == {"public-synthetic"}


def test_performance_statistics_are_in_range(catalogue: pd.DataFrame) -> None:
    traded = catalogue[catalogue["source"] == "scms"]
    assert traded["on_time_rate"].between(0, 1).all()
    assert (traded["avg_lead_days"] > 0).all()
    assert (traded["avg_unit_price"] >= 0).all()
    assert (traded["historical_volume"] > 0).all()


def test_on_time_rate_is_the_complement_of_the_late_rate() -> None:
    orders = load_scms(RAW_SCMS)
    catalogue = build_catalogue(orders, sap_dir=RAW_SAP_DIR)
    sample = catalogue[catalogue["source"] == "scms"].iloc[0]
    theirs = orders[orders["supplier_id"] == sample["supplier_id"]]
    assert sample["on_time_rate"] == pytest.approx(1 - theirs["is_late"].mean())
    assert sample["orders"] == len(theirs)


def test_lead_time_percentile_is_at_least_the_average(catalogue: pd.DataFrame) -> None:
    traded = catalogue[catalogue["source"] == "scms"]
    assert (traded["p75_lead_days"] >= traded["avg_lead_days"] * 0.5).all()


def test_suppliers_without_history_are_marked_as_uncertain(catalogue: pd.DataFrame) -> None:
    """SAP vendors have no trading history with us, so their risk is unknown."""
    from_sap = catalogue[catalogue["source"] == "sap"]
    assert (from_sap["orders"] == 0).all()
    assert from_sap["has_history"].eq(False).all()

    traded = catalogue[catalogue["source"] == "scms"]
    assert traded["has_history"].all()


def test_build_is_deterministic(catalogue: pd.DataFrame) -> None:
    again = build_catalogue(load_scms(RAW_SCMS), sap_dir=RAW_SAP_DIR)
    pd.testing.assert_frame_equal(catalogue, again)


def test_lead_times_record_which_evidence_they_came_from(catalogue: pd.DataFrame) -> None:
    """Only 38% of orders carry a PO date, so most suppliers need a fallback.

    The fallback must be visible: a buyer comparing two suppliers should know
    whether a lead time is that supplier's own record or their group's average.
    """
    measured = catalogue[catalogue["has_history"]]
    assert set(measured["lead_days_source"].unique()) <= {"supplier", "group", "global"}
    assert (measured["lead_days_source"] == "supplier").sum() >= 50
    own = measured[measured["lead_days_source"] == "supplier"]
    assert (own["lead_observations"] >= 3).all()


def test_lead_times_vary_across_suppliers(catalogue: pd.DataFrame) -> None:
    """A single global constant would flatten the differences the optimiser trades off."""
    measured = catalogue[catalogue["has_history"]]
    assert measured["avg_lead_days"].std() > 20
    assert measured["avg_lead_days"].nunique() > 20
    assert (measured["avg_lead_days"] > 0).all()


def test_suppliers_without_history_have_no_invented_lead_time(catalogue: pd.DataFrame) -> None:
    from_sap = catalogue[~catalogue["has_history"]]
    assert from_sap["avg_lead_days"].isna().all()
    assert (from_sap["lead_days_source"] == "none").all()
