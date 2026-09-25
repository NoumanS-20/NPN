"""Supplier offers — what each supplier can do for a specific material.

These tests exist because the first two versions of this table made the
optimisation meaningless: capacity was so large that no constraint ever bound.
They pin the scale, not just the shape.
"""

from __future__ import annotations

import pandas as pd
import pytest
from supplyguard.config import RAW_SAP_DIR, RAW_SCMS, SEED, TARGET_SUPPLIER_COUNT, TOP_PLANTS
from supplyguard.etl.asl import build_asl, ensure_coverage
from supplyguard.etl.offers import OFFER_COLUMNS, build_offers, coverage
from supplyguard.etl.plants import derive_plants
from supplyguard.etl.requirements import build_plan
from supplyguard.etl.scms import load_scms
from supplyguard.etl.suppliers import build_catalogue
from supplyguard.etl.synthesize import expand_suppliers


@pytest.fixture(scope="module")
def pipeline() -> dict[str, pd.DataFrame]:
    orders = load_scms(RAW_SCMS)
    suppliers = expand_suppliers(
        build_catalogue(orders, sap_dir=RAW_SAP_DIR),
        orders,
        target_total=TARGET_SUPPLIER_COUNT,
        seed=SEED,
    )
    plants = derive_plants(orders, top_n=TOP_PLANTS)
    requirements = build_plan(orders, plants, horizon_weeks=8)
    asl = build_asl(orders, suppliers, plants, requirements=requirements, seed=SEED)
    asl, offers = ensure_coverage(
        orders, suppliers, plants, requirements, asl, build_offers
    )
    return {
        "orders": orders, "suppliers": suppliers, "plants": plants,
        "requirements": requirements, "asl": asl, "offers": offers,
    }


def test_one_offer_per_approved_row(pipeline: dict[str, pd.DataFrame]) -> None:
    offers, asl = pipeline["offers"], pipeline["asl"]
    assert len(offers) == len(asl)
    assert not offers.duplicated(subset=["supplier_id", "material_id", "plant_id"]).any()


def test_contract_columns_are_present(pipeline: dict[str, pd.DataFrame]) -> None:
    assert set(pipeline["offers"].columns) >= OFFER_COLUMNS


def test_every_offer_is_usable(pipeline: dict[str, pd.DataFrame]) -> None:
    offers = pipeline["offers"]
    assert (offers["unit_price"] > 0).all()
    assert (offers["capacity_per_week"] > 0).all()
    assert (offers["lead_days"] > 0).all()
    assert (offers["moq"] >= 0).all()
    assert offers[["unit_price", "capacity_per_week", "lead_days"]].notna().all().all()


def test_minimum_order_never_exceeds_a_fifth_of_capacity(pipeline: dict[str, pd.DataFrame]) -> None:
    offers = pipeline["offers"]
    assert (offers["moq"] <= offers["capacity_per_week"] * 0.2 + 1).all()


def test_every_requirement_can_be_met(pipeline: dict[str, pd.DataFrame]) -> None:
    """An infeasible problem demonstrates nothing.

    Coverage must clear the requirement with room for the concentration cap to
    bind, which is why the approved list is topped up after offers are built.
    """
    cov = coverage(pipeline["offers"], pipeline["requirements"])
    assert (cov["coverage_ratio"] >= 1.3).all()


def test_capacity_is_not_so_large_that_it_stops_mattering(
    pipeline: dict[str, pd.DataFrame],
) -> None:
    """Regression on the scale of capacity.

    Supplier-level capacity gave 86x to 3,212x the weekly requirement, and a
    peak-week measure gave 60x to 2,285x. With constraints that loose the
    optimiser just picks the cheapest row and a supplier outage changes nothing.
    Capacity is now a sustainable weekly rate per supplier and material.
    """
    cov = coverage(pipeline["offers"], pipeline["requirements"])
    assert cov["coverage_ratio"].median() < 20
    assert cov["largest_share"].median() < 10


def test_prices_differ_within_a_material(pipeline: dict[str, pd.DataFrame]) -> None:
    """If every supplier charged the same, there would be nothing to optimise."""
    offers = pipeline["offers"]
    spread = offers.groupby(["material_id", "plant_id"])["unit_price"].agg(["min", "max"])
    assert ((spread["max"] / spread["min"]) > 1.1).mean() > 0.8


def test_generated_suppliers_get_offers_in_the_right_range(
    pipeline: dict[str, pd.DataFrame],
) -> None:
    offers = pipeline["offers"]
    real = offers[offers["origin"] == "real"]
    generated = offers[offers["origin"] == "synthetic"]
    assert len(generated) > 0
    ratio = generated["unit_price"].median() / real["unit_price"].median()
    assert 0.4 < ratio < 2.5


def test_build_is_deterministic(pipeline: dict[str, pd.DataFrame]) -> None:
    again = build_offers(
        pipeline["orders"], pipeline["suppliers"], pipeline["asl"],
        plants=pipeline["plants"], requirements=pipeline["requirements"], seed=SEED,
    )
    pd.testing.assert_frame_equal(pipeline["offers"], again)
