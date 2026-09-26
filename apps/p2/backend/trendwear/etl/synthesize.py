"""Extend the real styles into a TrendWear catalogue, and build the network.

The real file holds 20 clothing styles with two years of history. TrendWear
launches a new line every six weeks, which 20 styles cannot show, so we generate
the rest of the catalogue from the real styles' own behaviour: their seasonality,
their volume distribution, their price points and the shape of a launch.

What is generated and what is not:

* **Real styles keep their real history.** Forecast accuracy is reported on them
  alone, so nothing here can flatter a model.
* **Generated styles** are labelled `synthetic` in every table and on screen.
  They exist so the S&OP cycle, the capacity squeeze and the cold-start
  forecast have a realistic catalogue to work on.
* **The network** — plants, distribution centres, store lanes, the fabric bill
  of materials — is not in the source at all. Every value is derived and listed
  in `docs/assumptions.md`.

Everything is seeded, so the demo produces the same catalogue every time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trendwear.config import LAUNCH_CADENCE_WEEKS, SEED, TARGET_STYLE_COUNT

SEASONS = ("Spring/Summer", "Autumn/Winter", "Resort")

CATEGORIES = (
    ("Tee", 1.1, 0.35),
    ("Shirt", 1.9, 0.42),
    ("Dress", 2.4, 0.48),
    ("Trouser", 2.1, 0.45),
    ("Knitwear", 2.8, 0.52),
    ("Jacket", 3.4, 0.55),
)

FABRICS = (
    ("cotton-jersey", 6.20),
    ("cotton-poplin", 7.10),
    ("viscose-crepe", 8.40),
    ("wool-blend", 12.60),
    ("denim-12oz", 9.80),
    ("technical-shell", 15.30),
)

_ADJECTIVE = ("Harbour", "Meadow", "Atlas", "Solstice", "Corso", "Linden", "Brio", "Vale",
              "Anvil", "Quay", "Mistral", "Cinder", "Fable", "Noon", "Orchard", "Pike")


def build_style_catalogue(
    weekly: pd.DataFrame,
    n_styles: int = TARGET_STYLE_COUNT,
    seed: int = SEED,
) -> pd.DataFrame:
    """One row per style: what it is, when it launches, what it costs to make."""
    rng = np.random.default_rng(seed)
    # Costs draw from their own stream so that fixing the margin does not
    # shift every generated price and volume that came after it.
    cost_rng = np.random.default_rng(seed + 11)

    real_ids = sorted(weekly["style_id"].unique())
    real_volume = weekly.groupby("style_id")["units"].mean()
    real_price = weekly.groupby("style_id")["price"].mean()

    rows: list[dict[str, object]] = []

    for index, style_id in enumerate(real_ids):
        category, fabric_metres, cost_ratio = CATEGORIES[index % len(CATEGORIES)]
        fabric, fabric_price = FABRICS[index % len(FABRICS)]
        price = float(real_price.get(style_id, 50.0))
        # A tee and a jacket do not carry the same margin, and two jackets do
        # not carry the same margin either. A catalogue where every style
        # returns exactly 58% is a catalogue nobody believes.
        ratio = float(np.clip(cost_ratio * cost_rng.normal(1.0, 0.08), 0.25, 0.75))
        rows.append({
            "style_id": style_id,
            "name": f"{_ADJECTIVE[index % len(_ADJECTIVE)]} {category}",
            "category": category,
            "season": SEASONS[index % len(SEASONS)],
            "launch_week": (index // 3) * LAUNCH_CADENCE_WEEKS,
            "price": round(price, 2),
            "cost": round(price * ratio, 2),
            "fabric_id": fabric,
            "fabric_metres": fabric_metres,
            "fabric_price": fabric_price,
            "baseline_weekly_units": round(float(real_volume.get(style_id, 1000.0)), 1),
            "target_sell_through": 0.85,
            "origin": "real",
        })

    # Generated styles resample the real population rather than invent a shape.
    needed = max(n_styles - len(rows), 0)
    for index in range(needed):
        position = len(rows) + index
        category, fabric_metres, cost_ratio = CATEGORIES[position % len(CATEGORIES)]
        fabric, fabric_price = FABRICS[position % len(FABRICS)]
        ratio = float(np.clip(cost_ratio * cost_rng.normal(1.0, 0.08), 0.25, 0.75))

        price = float(rng.choice(real_price.to_numpy()) * rng.normal(1.0, 0.18))
        volume = float(rng.choice(real_volume.to_numpy()) * rng.normal(1.0, 0.30))

        rows.append({
            "style_id": f"GEN{index:04d}",
            # The name has to agree with the category. "Harbour Tee" filed
            # under Dress reads as a bug to anyone glancing at the screen.
            "name": f"{_ADJECTIVE[position % len(_ADJECTIVE)]} {category}",
            "category": category,
            "season": SEASONS[position % len(SEASONS)],
            "launch_week": (position // 3) * LAUNCH_CADENCE_WEEKS,
            "price": round(max(price, 8.0), 2),
            "cost": round(max(price, 8.0) * ratio, 2),
            "fabric_id": fabric,
            "fabric_metres": fabric_metres,
            "fabric_price": fabric_price,
            "baseline_weekly_units": round(max(volume, 50.0), 1),
            "target_sell_through": 0.85,
            "origin": "synthetic",
        })

    catalogue = pd.DataFrame(rows)
    catalogue["margin_pct"] = (
        (catalogue["price"] - catalogue["cost"]) / catalogue["price"]
    ).round(4)
    return catalogue


def simulate_sales(
    catalogue: pd.DataFrame,
    weekly: pd.DataFrame,
    launch_shape: np.ndarray,
    seed: int = SEED,
) -> pd.DataFrame:
    """Weekly history for generated styles, in the same shape as the real rows.

    Built from the real seasonal index and the real launch curve, with noise
    drawn from the variability the real styles actually show — so a generated
    style is a plausible member of the population, not a smooth line a model
    would find suspiciously easy to fit.
    """
    rng = np.random.default_rng(seed + 1)

    weeks = sorted(weekly["week_index"].unique())
    week_starts = weekly.drop_duplicates("week_index").set_index("week_index")["week_start"]
    seasonal = (
        weekly.groupby(weekly["week_start"].dt.isocalendar().week)["units"].mean()
    )
    seasonal = (seasonal / seasonal.mean()).clip(0.7, 1.4)

    # How noisy a real style is, week to week, once its level is removed.
    noise_scale = float(
        weekly.groupby("style_id")["units"].apply(lambda s: s.std() / max(s.mean(), 1)).median()
    )

    generated = catalogue[catalogue["origin"] == "synthetic"]
    rows: list[dict[str, object]] = []

    for style in generated.itertuples():
        for week in weeks:
            age = week - style.launch_week
            if age < 0:
                continue                      # not launched yet

            start = week_starts.get(week)
            shape = launch_shape[age] if age < len(launch_shape) else launch_shape[-1]
            season_factor = float(seasonal.get(start.isocalendar().week, 1.0))
            noise = float(rng.normal(1.0, noise_scale))

            units = style.baseline_weekly_units * shape * season_factor * max(noise, 0.15)
            discount = float(rng.choice([0.0, 0.0, 0.05, 0.1, 0.15, 0.2]))

            rows.append({
                "style_id": style.style_id,
                "store_id": "network",
                "week_start": start,
                "week_index": week,
                "units": round(units, 1),
                "observations": 7,
                "observed_units": round(units, 1),
                "price": style.price * (1 - discount),
                "discount_pct": discount,
                "competitor_price": round(style.price * float(rng.normal(1.0, 0.05)), 2),
                "inventory": round(units * float(rng.uniform(1.5, 4.0))),
                "ordered": 0.0,
                "promo_weeks": int(discount > 0),
                "seasonality": "Generated",
                "origin": "synthetic",
            })

    return pd.DataFrame(rows)


def build_network(catalogue: pd.DataFrame, seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Plants, distribution centres, store lanes and the fabric bill of materials.

    None of this is in the source file; all of it is required by the use case.
    Transit times and costs scale with distance band, capacity is sized against
    the catalogue's own demand, and every figure is in `docs/assumptions.md`.
    """
    rng = np.random.default_rng(seed + 2)

    plants = pd.DataFrame([
        {"plant_id": "plant-dhaka", "name": "Dhaka", "weekly_capacity_units": 42_000},
        {"plant_id": "plant-tirupur", "name": "Tirupur", "weekly_capacity_units": 31_000},
        {"plant_id": "plant-porto", "name": "Porto", "weekly_capacity_units": 14_000},
    ])

    regions = ("North", "South", "East", "West", "Central")
    dcs = pd.DataFrame([
        {"dc_id": f"dc-{region.lower()}", "name": f"{region} DC", "region": region}
        for region in regions
    ])

    stores = pd.DataFrame([
        {"store_id": f"S{index + 1:03d}", "region": region, "dc_id": f"dc-{region.lower()}"}
        for index, region in enumerate(regions)
    ])

    lanes = []
    for store in stores.itertuples():
        band = int(rng.integers(1, 4))        # 1 near, 3 far
        lanes.append({
            "dc_id": store.dc_id,
            "store_id": store.store_id,
            "distance_band": band,
            "transit_days": band * 2 + 1,
            "cost_per_unit": round(0.35 + band * 0.22, 2),
            "mode": "Road" if band < 3 else "Rail",
        })

    bom = (
        catalogue[["style_id", "fabric_id", "fabric_metres", "fabric_price"]]
        .assign(
            # Minimum order quantities are set per fabric, in metres, at a level
            # a mill would actually accept.
            fabric_moq_metres=lambda df: np.where(df["fabric_price"] > 10, 2_000, 5_000),
        )
        .copy()
    )

    return {
        "plants": plants,
        "dcs": dcs,
        "stores": stores,
        "lanes": pd.DataFrame(lanes),
        "fabric_bom": bom,
    }


def summarise(catalogue: pd.DataFrame, sales: pd.DataFrame) -> dict[str, float | int]:
    real = catalogue[catalogue["origin"] == "real"]
    generated = catalogue[catalogue["origin"] == "synthetic"]
    return {
        "styles_total": int(len(catalogue)),
        "styles_real": int(len(real)),
        "styles_generated": int(len(generated)),
        "seasons": int(catalogue["season"].nunique()),
        "launch_weeks": int(catalogue["launch_week"].nunique()),
        "generated_rows": int(len(sales)),
        "median_price_real": round(float(real["price"].median()), 2),
        "median_price_generated": round(float(generated["price"].median()), 2),
        "fabrics": int(catalogue["fabric_id"].nunique()),
    }
