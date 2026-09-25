"""Build supplier offers: what each supplier can do **for a given material**.

The supplier catalogue answers "how does this supplier behave in general". The
optimiser needs something narrower: how much of *this material* can *this
supplier* deliver in a week, at what price, with what minimum order.

That distinction turned out to matter a great deal. Using supplier-level
capacity, the approved base held 86x to 3,212x the weekly requirement for a
material, and a single supplier could cover 125x it. Capacity, minimum order
quantities and contract limits never bound, so the "optimiser" was really just
picking the cheapest row — and the scenario demo would have shown nothing when a
supplier was removed. Capacity per supplier *and material* restores the tension
the use case is actually about.

Offers come from two places:

* **traded** — measured from that supplier's real shipments of that material.
* **qualified** — for generated suppliers, drawn from what the material's real
  offers look like, then shifted by that supplier's own price and reliability
  profile so they remain distinguishable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from supplyguard.config import SEED

OFFER_COLUMNS: set[str] = {
    "supplier_id", "material_id", "plant_id", "unit_price", "lead_days",
    "capacity_per_week", "moq", "qualification", "origin",
}

# Headroom above a supplier's sustainable weekly rate. Enough that a plan is
# always feasible, small enough that capacity still binds.
_CAPACITY_HEADROOM = 2.0


def _traded_offers(orders: pd.DataFrame) -> pd.DataFrame:
    """Per supplier and material, measured from real shipments.

    Capacity is the **sustainable weekly rate** — everything that supplier shipped
    of that material, divided by the weeks in the record, doubled for headroom.

    Not the 95th percentile of a week: pharmaceutical procurement ships in bulk,
    so a supplier's best week can hold a quarter's volume. Using that peak gave
    offers 60x to 2,285x the weekly requirement and every single supplier could
    cover a plant alone, which makes capacity constraints decorative and a
    supplier-outage scenario a non-event. A sustainable rate is directly
    comparable to the consumption the requirement plan is built from.
    """
    dated = orders.dropna(subset=["promised_date"]).copy()
    span_weeks = max((dated["promised_date"].max() - dated["promised_date"].min()).days / 7.0, 1.0)

    totals = dated.groupby(["supplier_id", "item"])["qty"].sum()
    capacity = (totals / span_weeks) * _CAPACITY_HEADROOM

    stats = dated.groupby(["supplier_id", "item"]).agg(
        unit_price=("unit_price", "median"),
        moq=("qty", lambda s: s.quantile(0.10)),
        shipments=("po_id", "size"),
    )
    stats["capacity_per_week"] = capacity
    return stats.reset_index().rename(columns={"item": "material_id"})


def build_offers(
    orders: pd.DataFrame,
    suppliers: pd.DataFrame,
    asl: pd.DataFrame,
    seed: int = SEED,
) -> pd.DataFrame:
    """One row per approved supplier, material and plant."""
    rng = np.random.default_rng(seed)

    traded = _traded_offers(orders)
    offers = asl.merge(traded, on=["supplier_id", "material_id"], how="left")

    # What a typical offer for this material looks like, used for suppliers
    # qualified on the material but with no shipments of their own.
    material_price = traded.groupby("material_id")["unit_price"].median()
    material_capacity = traded.groupby("material_id")["capacity_per_week"].median()
    material_moq = traded.groupby("material_id")["moq"].median()

    supplier_profile = suppliers.set_index("supplier_id")
    price_index = (
        supplier_profile["avg_unit_price"]
        / supplier_profile.groupby("product_group")["avg_unit_price"].transform("median")
    ).clip(0.6, 1.6)

    missing = offers["unit_price"].isna()
    n_missing = int(missing.sum())
    if n_missing:
        base_price = offers.loc[missing, "material_id"].map(material_price)
        shift = offers.loc[missing, "supplier_id"].map(price_index).fillna(1.0)
        noise = rng.normal(1.0, 0.08, n_missing).clip(0.8, 1.25)
        offers.loc[missing, "unit_price"] = (base_price * shift * noise).astype(float)

        base_capacity = offers.loc[missing, "material_id"].map(material_capacity)
        capacity_noise = rng.normal(1.0, 0.25, n_missing).clip(0.5, 1.8)
        offers.loc[missing, "capacity_per_week"] = (base_capacity * capacity_noise).astype(float)

        offers.loc[missing, "moq"] = offers.loc[missing, "material_id"].map(material_moq)

    offers["lead_days"] = offers["supplier_id"].map(supplier_profile["avg_lead_days"])
    offers["p75_lead_days"] = offers["supplier_id"].map(supplier_profile["p75_lead_days"])
    offers["origin"] = offers["supplier_id"].map(supplier_profile["origin"])
    offers["on_time_rate"] = offers["supplier_id"].map(supplier_profile["on_time_rate"])

    # Fill the last gaps from the material's own middle, then clean up.
    for column, source in (
        ("unit_price", material_price),
        ("capacity_per_week", material_capacity),
        ("moq", material_moq),
    ):
        offers[column] = offers[column].fillna(offers["material_id"].map(source))
        offers[column] = offers[column].fillna(float(traded[column].median()))

    offers["unit_price"] = offers["unit_price"].clip(lower=0.01).round(4)
    offers["capacity_per_week"] = offers["capacity_per_week"].clip(lower=1).round()
    # A minimum order above a fifth of weekly capacity would exclude the supplier
    # from most weeks, which is a modelling artefact rather than a real term.
    offers["moq"] = np.minimum(
        offers["moq"].fillna(0).clip(lower=0), offers["capacity_per_week"] * 0.2
    ).round()
    offers["lead_days"] = offers["lead_days"].fillna(float(suppliers["avg_lead_days"].median()))
    offers["shipments"] = offers["shipments"].fillna(0).astype(int)

    columns = [
        "supplier_id", "material_id", "plant_id", "unit_price", "lead_days",
        "p75_lead_days", "capacity_per_week", "moq", "shipments", "on_time_rate",
        "qualification", "origin",
    ]
    return (
        offers[columns]
        .sort_values(["plant_id", "material_id", "unit_price"], kind="mergesort")
        .reset_index(drop=True)
    )


def coverage(offers: pd.DataFrame, requirements: pd.DataFrame) -> pd.DataFrame:
    """Approved weekly capacity against the peak weekly requirement."""
    available = offers.groupby(["material_id", "plant_id"])["capacity_per_week"].sum()
    largest = offers.groupby(["material_id", "plant_id"])["capacity_per_week"].max()
    need = requirements.groupby(["material_id", "plant_id"])["required_qty"].max()

    out = pd.concat(
        {"approved_capacity": available, "largest_supplier": largest, "peak_need": need},
        axis=1,
    ).dropna()
    out["coverage_ratio"] = out["approved_capacity"] / out["peak_need"]
    out["largest_share"] = out["largest_supplier"] / out["peak_need"]
    return out


def summarise(offers: pd.DataFrame) -> dict[str, float | int]:
    return {
        "offers": int(len(offers)),
        "traded_offers": int((offers["qualification"] == "traded").sum()),
        "qualified_offers": int((offers["qualification"] == "qualified").sum()),
        "median_unit_price": round(float(offers["unit_price"].median()), 4),
        "median_capacity_per_week": float(offers["capacity_per_week"].median()),
        "median_moq": float(offers["moq"].median()),
        "median_lead_days": float(offers["lead_days"].median()),
    }
