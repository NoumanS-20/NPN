"""Build the approved supplier list.

A buyer cannot source from whoever is cheapest; they can source from suppliers
approved for that material at that plant. The official use case lists an
"approved supplier list" as an input, and it is what keeps the allocation
believable — every line the optimiser produces is one a procurement team could
actually place.

Two ways onto the list:

* **traded** — the supplier has delivered that material before. Evidence, not
  assumption.
* **qualified** — a generated supplier cleared for materials in its own product
  group. Generated suppliers exist to make the comparison large, so they are
  qualified for the materials their group buys.

Suppliers from the SAP vendor master are deliberately *not* approved: we have no
trading history with them and no product classification, so approving them would
mean inventing a qualification that does not exist.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from supplyguard.config import SEED

# Every material needs a real choice of suppliers, or "allocation" is a
# formality. Where trading history alone does not provide that, qualified
# suppliers from the same product group fill the gap.
MIN_SUPPLIERS_PER_MATERIAL = 6

# Approved capacity must comfortably exceed the peak weekly requirement, or the
# optimiser is handed an infeasible problem. 1.5x leaves room for the minimum
# order quantities and the concentration cap to bind without making demand
# impossible to meet — which is exactly the tension the use case is about.
CAPACITY_COVERAGE_TARGET = 1.5


def _traded_pairs(orders: pd.DataFrame, plant_ids: set[str]) -> pd.DataFrame:
    """Supplier-material-plant combinations that really happened."""
    tagged = orders[orders["plant_id"].isin(plant_ids)] if "plant_id" in orders else orders
    traded = (
        tagged.groupby(["supplier_id", "item", "plant_id"], as_index=False)
        .agg(orders_placed=("po_id", "size"), first_order=("promised_date", "min"))
        .rename(columns={"item": "material_id"})
    )
    traded["qualification"] = "traded"
    traded["approved_since"] = traded["first_order"]
    return traded.drop(columns="first_order")


def build_asl(
    orders: pd.DataFrame,
    suppliers: pd.DataFrame,
    plants: pd.DataFrame,
    requirements: pd.DataFrame | None = None,
    seed: int = SEED,
) -> pd.DataFrame:
    """Return one row per approved supplier, material and plant."""
    rng = np.random.default_rng(seed)

    from supplyguard.etl.plants import attach_plant_id

    tagged = attach_plant_id(orders, plants)
    plant_ids = set(plants["plant_id"])

    traded = _traded_pairs(tagged, plant_ids)

    if requirements is not None:
        wanted = set(zip(requirements["material_id"], requirements["plant_id"], strict=True))
        traded = traded[
            [pair in wanted for pair in zip(traded["material_id"], traded["plant_id"], strict=True)]
        ]

    # Which product group each material belongs to, so generated suppliers are
    # qualified for materials their group actually supplies.
    material_group = (
        tagged.groupby("item")["product_group"].agg(lambda s: s.value_counts().index[0]).to_dict()
    )

    generated = suppliers[suppliers["origin"] == "synthetic"]
    by_group: dict[str, list[str]] = {
        group: rows["supplier_id"].tolist()
        for group, rows in generated.groupby("product_group")
    }

    capacity = suppliers.set_index("supplier_id")["capacity_per_week"].to_dict()
    peak_need = (
        requirements.groupby(["material_id", "plant_id"])["required_qty"].max().to_dict()
        if requirements is not None
        else {}
    )

    earliest = orders["promised_date"].min()
    extra: list[dict[str, object]] = []

    for (material, plant), rows in traded.groupby(["material_id", "plant_id"]):
        approved = rows["supplier_id"].tolist()
        pool = [s for s in by_group.get(material_group.get(material, ""), []) if s not in approved]
        if not pool:
            continue

        need = peak_need.get((material, plant), 0.0)
        available = sum(capacity.get(s, 0.0) for s in approved)

        # Qualify suppliers until there is both a real choice and enough capacity
        # to serve the peak week. A procurement team does the same thing: when the
        # approved base cannot cover demand, you qualify more suppliers.
        order = list(rng.permutation(pool))
        picked: list[str] = []
        for supplier_id in order:
            enough_choice = len(approved) + len(picked) >= MIN_SUPPLIERS_PER_MATERIAL
            enough_capacity = available >= need * CAPACITY_COVERAGE_TARGET
            if enough_choice and enough_capacity:
                break
            picked.append(supplier_id)
            available += capacity.get(supplier_id, 0.0)

        extra.extend(
            {
                "supplier_id": supplier_id,
                "material_id": material,
                "plant_id": plant,
                "orders_placed": 0,
                "qualification": "qualified",
                "approved_since": earliest,
            }
            for supplier_id in picked
        )

    asl = pd.concat([traded, pd.DataFrame(extra)], ignore_index=True, sort=False)
    asl = asl.drop_duplicates(subset=["supplier_id", "material_id", "plant_id"])
    asl["orders_placed"] = asl["orders_placed"].fillna(0).astype(int)

    return asl.sort_values(
        ["plant_id", "material_id", "qualification", "supplier_id"], kind="mergesort"
    ).reset_index(drop=True)


def summarise(asl: pd.DataFrame) -> dict[str, float | int]:
    per_pair = asl.groupby(["material_id", "plant_id"])["supplier_id"].nunique()
    return {
        "approvals": int(len(asl)),
        "traded": int((asl["qualification"] == "traded").sum()),
        "qualified": int((asl["qualification"] == "qualified").sum()),
        "material_plant_pairs": int(len(per_pair)),
        "min_suppliers_per_pair": int(per_pair.min()),
        "median_suppliers_per_pair": float(per_pair.median()),
        "max_suppliers_per_pair": int(per_pair.max()),
    }
