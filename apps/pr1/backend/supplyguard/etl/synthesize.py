"""Expand the supplier base and attach commercial terms.

Two jobs, both honest about what they invent:

**Commercial terms.** Real procurement data records what was bought, not the
contract behind it. SCMS has no minimum order quantity, no supplier capacity and
no contract bands, yet all three are constraints the use case explicitly names.
We derive them from each supplier's own trading history — a supplier that has
never shipped more than 5,000 units in a period does not suddenly have capacity
for 50,000 — and record every formula in ``docs/assumptions.md``.

**Generated suppliers.** 217 real supplier entities is a real allocation problem,
but the mentor asked for hundreds of suppliers to compare. We generate the rest
by sampling each product group's real distributions, so a generated supplier is a
plausible member of the population rather than random noise.

Rules we hold to:

* Real rows are never modified, only extended with terms.
* Every generated row is ``origin = "synthetic"``, visible in the UI.
* Reported model metrics filter to real rows, so generated data can make the
  problem larger but never make a score look better.
* Generation is seeded, so the demo is reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from supplyguard.config import SEED

TERMS_COLUMNS: set[str] = {
    "moq", "capacity_per_week", "contract_min_share", "contract_max_share",
}

# Name parts for generated suppliers. Deliberately plain: a generated supplier
# should be identifiable as generated at a glance.
_PREFIX = (
    "Meridian", "Northwind", "Cobalt", "Ardent", "Vertex", "Solstice", "Kestrel",
    "Ironwood", "Lumen", "Pinnacle", "Sable", "Torrent", "Juniper", "Halcyon",
    "Quarry", "Bastion", "Cinder", "Delta Ridge", "Ember", "Foundry",
)
_SUFFIX = (
    "Pharmaceuticals", "Labs", "Biologics", "Manufacturing", "Industries",
    "Life Sciences", "Chemicals", "Health", "Diagnostics", "Supply Co",
)
_SITE = (
    "Unit I", "Unit II", "Unit III", "Plant A", "Plant B", "Works 1", "Works 2",
    "Facility North", "Facility South", "Export Unit",
)


def _weekly_volume(orders: pd.DataFrame) -> pd.Series:
    """Units per supplier per active week — the basis for weekly capacity.

    Planning happens by week, so capacity has to be a weekly number. An earlier
    version used quarterly volume, which left every supplier with 245x to
    11,844x the weekly requirement: capacity, minimum orders and contracts never
    bound, and the optimiser degenerated into "pick the cheapest". Weekly p95
    puts the median supplier at about 2,000 units a week against typical
    requirement lines of 3,700, so the constraints do real work.
    """
    working = orders.dropna(subset=["promised_date"]).copy()
    working["week"] = working["promised_date"].dt.to_period("W")
    return working.groupby(["supplier_id", "week"])["qty"].sum()


def attach_commercial_terms(
    catalogue: pd.DataFrame,
    orders: pd.DataFrame,
    seed: int = SEED,
) -> pd.DataFrame:
    """Add MOQ, capacity and contract bands, derived from trading history.

    * **capacity_per_week** — the 95th percentile of that supplier's weekly
      shipped volume, scaled by 1.5 to allow headroom. A supplier with no history
      of their own inherits their product group's median.
    * **moq** — the 10th percentile of their order quantities, rounded, and never
      above a fifth of capacity, so a minimum never makes a supplier unusable.
    * **contract bands** — built around each supplier's historical share of their
      product group: a floor at a quarter of that share, a ceiling at twice it,
      capped at 60% so no contract mandates single sourcing.
    """
    rng = np.random.default_rng(seed)
    out = catalogue.copy()

    per_week = _weekly_volume(orders)
    capacity = per_week.groupby("supplier_id").quantile(0.95) * 1.5
    moq = orders.groupby("supplier_id")["qty"].quantile(0.10)

    out["capacity_per_week"] = out["supplier_id"].map(capacity)
    out["moq"] = out["supplier_id"].map(moq)

    # Suppliers with no history of their own take their group's middle.
    group_capacity = out.groupby("product_group")["capacity_per_week"].transform("median")
    global_capacity = float(out["capacity_per_week"].median(skipna=True))
    out["capacity_per_week"] = out["capacity_per_week"].fillna(group_capacity).fillna(
        global_capacity
    )
    group_moq = out.groupby("product_group")["moq"].transform("median")
    out["moq"] = out["moq"].fillna(group_moq).fillna(float(out["moq"].median(skipna=True)))

    out["capacity_per_week"] = out["capacity_per_week"].clip(lower=100).round()
    out["moq"] = out["moq"].fillna(0).clip(lower=0).round()
    # A minimum order larger than a fifth of capacity would exclude the supplier
    # from most plans, which is a modelling artefact rather than a real term.
    out["moq"] = np.minimum(out["moq"], out["capacity_per_week"] * 0.2).round()

    volume = out["historical_volume"].fillna(0.0)
    group_total = out.groupby("product_group")["historical_volume"].transform("sum")
    share = (volume / group_total.replace(0, np.nan)).fillna(1.0 / len(out))

    out["contract_min_share"] = (share * 0.25).clip(0.0, 0.10).round(4)
    # The ceiling must never be tighter than the concentration cap the planner
    # works to, or the two rules contradict each other and no plan exists.
    #
    # Two earlier versions got this wrong. Taken straight from historical share,
    # ceilings averaged 5% and capped total available volume at about 30% of
    # demand. Raised to a 25% floor, they still bound tighter than the 40%
    # concentration cap: on one line two substantial suppliers were held to 116
    # units each against a requirement of 464, and the plan was infeasible for a
    # reason that had nothing to do with sourcing.
    #
    # The floor now sits above the default cap. Single sourcing is prevented by
    # the concentration cap and the minimum supplier count, which is where that
    # rule belongs.
    out["contract_max_share"] = (share * 2.0).clip(0.50, 0.80).round(4)
    # Keep the band ordered even where a supplier's share is tiny.
    out["contract_max_share"] = np.maximum(
        out["contract_max_share"], out["contract_min_share"] + 0.05
    ).round(4)

    # A little spread so contracts are not all identical multiples of history.
    jitter = rng.normal(1.0, 0.05, size=len(out)).clip(0.85, 1.15)
    out["contract_max_share"] = (out["contract_max_share"] * jitter).clip(0.05, 0.60).round(4)
    out["contract_max_share"] = np.maximum(
        out["contract_max_share"], out["contract_min_share"] + 0.05
    ).round(4)

    return out


def _sample_group_profile(
    rng: np.random.Generator,
    real_group: pd.DataFrame,
    fallback: pd.DataFrame,
    count: int,
) -> dict[str, np.ndarray]:
    """Draw plausible statistics for ``count`` new suppliers in one product group.

    We resample the real values and jitter them, rather than fitting a
    parametric distribution. Two reasons:

    * The real on-time rate is extremely skewed — a median of 100% with a long
      thin tail of poor performers. A fitted beta reproduced the mean or the
      spread, but never both, and an earlier version silently shifted the mean
      from 0.97 to 0.82, making every generated supplier look worse than reality.
    * Resampling is one line to explain in an interview: a generated supplier
      behaves like some real supplier, nudged.
    """

    def draw(column: str, spread: float, lower: float, upper: float) -> np.ndarray:
        values = real_group[column].dropna()
        if len(values) < 5:
            values = fallback[column].dropna()
        if len(values) == 0:
            return np.full(count, lower)
        picked = rng.choice(values.to_numpy(), size=count, replace=True)
        jittered = picked * rng.normal(1.0, spread, count)
        return np.clip(jittered, lower, upper)

    return {
        "on_time_rate": draw("on_time_rate", 0.03, 0.0, 1.0),
        "avg_lead_days": draw("avg_lead_days", 0.15, 7.0, 400.0),
        "avg_unit_price": draw("avg_unit_price", 0.20, 0.01, 1e6),
        "historical_volume": draw("historical_volume", 0.30, 100.0, 1e9).round(),
    }


def expand_suppliers(
    catalogue: pd.DataFrame,
    orders: pd.DataFrame,
    target_total: int = 520,
    seed: int = SEED,
) -> pd.DataFrame:
    """Return real suppliers plus enough generated ones to reach ``target_total``.

    Generated suppliers are distributed across product groups in proportion to
    the real population, so competition grows where it already exists.
    """
    rng = np.random.default_rng(seed)

    real = catalogue[catalogue["origin"] == "real"].copy()
    needed = max(target_total - len(real), 0)

    if needed == 0:
        return attach_commercial_terms(real, orders, seed=seed)

    weights = real["product_group"].value_counts(normalize=True)
    allocation = (weights * needed).round().astype(int)
    # Rounding can leave the total a little short or long; fix on the largest group.
    drift = needed - int(allocation.sum())
    if drift != 0:
        allocation.iloc[0] += drift

    rows: list[pd.DataFrame] = []
    counter = 1
    for group, count in allocation.items():
        if count <= 0:
            continue
        real_group = real[real["product_group"] == group]
        profile = _sample_group_profile(rng, real_group, real, int(count))

        names = [
            f"{_PREFIX[rng.integers(len(_PREFIX))]} {_SUFFIX[rng.integers(len(_SUFFIX))]}"
            f" — {_SITE[rng.integers(len(_SITE))]}"
            for _ in range(int(count))
        ]
        countries = rng.choice(
            real_group["country"].dropna().unique()
            if real_group["country"].notna().any()
            else np.array(["IN"]),
            size=int(count),
        )

        block = pd.DataFrame({
            "supplier_id": [f"gen-{i:04d}" for i in range(counter, counter + int(count))],
            "name": names,
            "country": countries,
            "product_group": group,
            "orders": rng.integers(3, 60, int(count)),
            "on_time_rate": profile["on_time_rate"],
            "avg_lead_days": profile["avg_lead_days"].round(1),
            "avg_unit_price": profile["avg_unit_price"].round(4),
            "historical_volume": profile["historical_volume"],
            "countries_served": 1,
            "defect_rate": np.nan,
            "lead_observations": rng.integers(3, 30, int(count)),
            "lead_days_source": "supplier",
            "has_history": True,
            "origin": "synthetic",
            "source": "generated",
        })
        block["p75_lead_days"] = (block["avg_lead_days"] * 1.25).round(1)
        block["historical_value"] = (
            block["historical_volume"] * block["avg_unit_price"]
        ).round(2)
        rows.append(block)
        counter += int(count)

    expanded = pd.concat([real, *rows], ignore_index=True, sort=False)
    expanded = expanded.sort_values(["origin", "supplier_id"], kind="mergesort").reset_index(
        drop=True
    )
    return attach_commercial_terms(expanded, orders, seed=seed)


def summarise(expanded: pd.DataFrame) -> dict[str, float | int]:
    real = expanded[expanded["origin"] == "real"]
    generated = expanded[expanded["origin"] == "synthetic"]
    return {
        "suppliers_total": int(len(expanded)),
        "real": int(len(real)),
        "generated": int(len(generated)),
        "median_moq": float(expanded["moq"].median()),
        "median_capacity_per_week": float(expanded["capacity_per_week"].median()),
        "median_contract_max_share": float(expanded["contract_max_share"].median()),
        "real_median_on_time": round(float(real["on_time_rate"].median()), 4),
        "generated_median_on_time": round(float(generated["on_time_rate"].median()), 4)
        if len(generated)
        else float("nan"),
    }
