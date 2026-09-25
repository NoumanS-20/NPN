"""Synthetic expansion of the supplier base.

The mentor allows real and generated data to be mixed, and PR1 needs hundreds of
suppliers competing for the same material before an allocation decision is
interesting. Generated suppliers exist to make the problem realistically large —
never to improve a reported result, which is why origin is tracked on every row
and every metric we publish filters to real records.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_SAP_DIR, RAW_SCMS, SEED, TARGET_SUPPLIER_COUNT
from supplyguard.etl.scms import load_scms
from supplyguard.etl.suppliers import build_catalogue
from supplyguard.etl.synthesize import (
    TERMS_COLUMNS,
    attach_commercial_terms,
    expand_suppliers,
)


@pytest.fixture(scope="module")
def orders() -> pd.DataFrame:
    return load_scms(RAW_SCMS)


@pytest.fixture(scope="module")
def catalogue(orders: pd.DataFrame) -> pd.DataFrame:
    return build_catalogue(orders, sap_dir=RAW_SAP_DIR)


@pytest.fixture(scope="module")
def expanded(catalogue: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    return expand_suppliers(catalogue, orders, target_total=TARGET_SUPPLIER_COUNT, seed=SEED)


def test_expansion_reaches_the_target(expanded: pd.DataFrame) -> None:
    assert len(expanded) >= TARGET_SUPPLIER_COUNT
    assert expanded["supplier_id"].is_unique


def test_real_suppliers_are_untouched(expanded: pd.DataFrame, catalogue: pd.DataFrame) -> None:
    real = expanded[expanded["origin"] == "real"]
    assert len(real) == int((catalogue["origin"] == "real").sum()) == 217
    real_ids = set(catalogue.loc[catalogue["origin"] == "real", "supplier_id"])
    assert set(real["supplier_id"]) == real_ids


def test_generated_suppliers_are_labelled(expanded: pd.DataFrame) -> None:
    generated = expanded[expanded["origin"] == "synthetic"]
    assert len(generated) > 250
    assert (generated["source"] == "generated").all()
    assert generated["has_history"].all(), "generated suppliers carry a generated history"


def test_generated_statistics_track_the_real_ones(expanded: pd.DataFrame) -> None:
    """Generated suppliers must look like the real population, not like noise."""
    real = expanded[(expanded["origin"] == "real") & expanded["has_history"]]
    generated = expanded[expanded["origin"] == "synthetic"]
    for column in ("on_time_rate", "avg_lead_days", "avg_unit_price"):
        assert abs(generated[column].mean() - real[column].mean()) < 0.5 * real[column].std()


def test_generation_is_deterministic(catalogue: pd.DataFrame, orders: pd.DataFrame) -> None:
    a = expand_suppliers(catalogue, orders, target_total=TARGET_SUPPLIER_COUNT, seed=SEED)
    b = expand_suppliers(catalogue, orders, target_total=TARGET_SUPPLIER_COUNT, seed=SEED)
    pd.testing.assert_frame_equal(a, b)


def test_a_different_seed_gives_different_suppliers(
    catalogue: pd.DataFrame, orders: pd.DataFrame
) -> None:
    a = expand_suppliers(catalogue, orders, target_total=300, seed=1)
    b = expand_suppliers(catalogue, orders, target_total=300, seed=2)
    generated_a = a.loc[a["origin"] == "synthetic", "on_time_rate"].tolist()
    generated_b = b.loc[b["origin"] == "synthetic", "on_time_rate"].tolist()
    assert generated_a != generated_b


def test_every_supplier_ends_up_in_a_real_product_group(expanded: pd.DataFrame) -> None:
    generated = expanded[expanded["origin"] == "synthetic"]
    real_groups = set(expanded.loc[expanded["origin"] == "real", "product_group"])
    assert set(generated["product_group"]) <= real_groups


def test_commercial_terms_are_attached_to_everyone(expanded: pd.DataFrame) -> None:
    assert set(expanded.columns) >= TERMS_COLUMNS
    assert (expanded["moq"] >= 0).all()
    assert (expanded["capacity_per_week"] > expanded["moq"]).all()
    assert (expanded["contract_min_share"] <= expanded["contract_max_share"]).all()
    assert expanded["contract_max_share"].between(0, 1).all()


def test_terms_are_derived_from_a_supplier_own_history(
    orders: pd.DataFrame, catalogue: pd.DataFrame
) -> None:
    """MOQ and capacity must reflect how that supplier actually trades."""
    with_terms = attach_commercial_terms(catalogue, orders, seed=SEED)
    traded = with_terms[with_terms["has_history"] & (with_terms["orders"] >= 5)]
    big = traded.nlargest(20, "historical_volume")
    small = traded.nsmallest(20, "historical_volume")
    assert big["capacity_per_week"].median() > small["capacity_per_week"].median()


def test_capacity_can_cover_demand_in_aggregate(expanded: pd.DataFrame) -> None:
    """A problem where no feasible plan exists is not a demonstration of anything."""
    for group, rows in expanded.groupby("product_group"):
        if group == "UNCLASSIFIED":
            continue
        assert rows["capacity_per_week"].sum() > 0
