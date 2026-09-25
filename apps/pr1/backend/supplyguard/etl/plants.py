"""Derive the plants that material is delivered to.

The official PR1 data spec asks for demand "by SKU/plant". SCMS ships to 43
countries; we treat the highest-volume destinations as plants, which is the same
structure a manufacturer's network has — several receiving sites, each with its
own demand and its own approved suppliers.

The mapping is stated openly in the README and on screen: delivery location →
plant. Nothing is renamed to look like something it is not.
"""

from __future__ import annotations

import re

import pandas as pd

_slug_re = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _slug_re.sub("-", str(value).strip().lower()).strip("-")


def derive_plants(orders: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """The ``top_n`` destinations by volume, as the plants we plan for."""
    grouped = orders.groupby("country").agg(
        historical_volume=("qty", "sum"),
        historical_value=("line_value", "sum"),
        orders=("po_id", "size"),
        materials=("item", "nunique"),
    )
    top = grouped.nlargest(top_n, "historical_volume").reset_index()

    return pd.DataFrame({
        "plant_id": ["plant-" + _slug(c) for c in top["country"]],
        "name": top["country"],
        "country": top["country"],
        "historical_volume": top["historical_volume"].astype(float),
        "historical_value": top["historical_value"].astype(float),
        "orders": top["orders"].astype(int),
        "materials": top["materials"].astype(int),
        "origin": "derived",
    })


def attach_plant_id(orders: pd.DataFrame, plants: pd.DataFrame) -> pd.DataFrame:
    """Tag each order with its plant, leaving other destinations unassigned."""
    lookup = dict(zip(plants["country"], plants["plant_id"], strict=True))
    out = orders.copy()
    out["plant_id"] = out["country"].map(lookup)
    return out
