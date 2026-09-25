"""The approved supplier list.

"Approved supplier list" is one of the inputs the official use case names. It is
also what makes the allocation realistic: a buyer cannot simply pick the cheapest
supplier on earth, only the cheapest one cleared to supply that material to that
plant.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_SAP_DIR, RAW_SCMS, SEED, TARGET_SUPPLIER_COUNT, TOP_PLANTS
from supplyguard.etl.asl import build_asl
from supplyguard.etl.plants import derive_plants
from supplyguard.etl.scms import load_scms
from supplyguard.etl.suppliers import build_catalogue
from supplyguard.etl.synthesize import expand_suppliers


@pytest.fixture(scope="module")
def orders() -> pd.DataFrame:
    return load_scms(RAW_SCMS)


@pytest.fixture(scope="module")
def suppliers(orders: pd.DataFrame) -> pd.DataFrame:
    catalogue = build_catalogue(orders, sap_dir=RAW_SAP_DIR)
    return expand_suppliers(catalogue, orders, target_total=TARGET_SUPPLIER_COUNT, seed=SEED)


@pytest.fixture(scope="module")
def asl(orders: pd.DataFrame, suppliers: pd.DataFrame) -> pd.DataFrame:
    plants = derive_plants(orders, top_n=TOP_PLANTS)
    return build_asl(orders, suppliers, plants, seed=SEED)


def test_rows_are_unique_per_supplier_material_plant(asl: pd.DataFrame) -> None:
    assert not asl.duplicated(subset=["supplier_id", "material_id", "plant_id"]).any()


def test_qualification_is_either_traded_or_qualified(asl: pd.DataFrame) -> None:
    assert set(asl["qualification"].unique()) <= {"traded", "qualified"}


def test_traded_approvals_reflect_real_orders(asl: pd.DataFrame, orders: pd.DataFrame) -> None:
    traded = asl[asl["qualification"] == "traded"]
    real_pairs = set(zip(orders["supplier_id"], orders["item"], strict=True))
    sample = traded.head(200)
    for row in sample.itertuples():
        assert (row.supplier_id, row.material_id) in real_pairs


def test_generated_suppliers_are_qualified_not_traded(asl: pd.DataFrame) -> None:
    generated = asl[asl["supplier_id"].str.startswith("gen-")]
    assert len(generated) > 0
    assert (generated["qualification"] == "qualified").all()


def test_every_material_and_plant_has_enough_approved_suppliers(asl: pd.DataFrame) -> None:
    """Two suppliers minimum, or the allocation has nothing to choose between."""
    per_pair = asl.groupby(["material_id", "plant_id"])["supplier_id"].nunique()
    assert per_pair.min() >= 2


def test_approvals_carry_a_date(asl: pd.DataFrame) -> None:
    assert asl["approved_since"].notna().all()


def test_unclassified_sap_vendors_are_not_approved(asl: pd.DataFrame) -> None:
    """A vendor from the ERP master with no product group cannot be approved."""
    assert not asl["supplier_id"].str.startswith("sap-").any()


def test_build_is_deterministic(orders: pd.DataFrame, suppliers: pd.DataFrame) -> None:
    plants = derive_plants(orders, top_n=TOP_PLANTS)
    a = build_asl(orders, suppliers, plants, seed=SEED)
    b = build_asl(orders, suppliers, plants, seed=SEED)
    pd.testing.assert_frame_equal(a, b)
