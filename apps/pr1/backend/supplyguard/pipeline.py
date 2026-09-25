"""Assemble everything SupplyGuard needs to answer a question.

The ETL, the supplier expansion, the risk model and the offer table are built
once and cached. The API then loads that cache at startup and serves from
memory, so a request never waits on a model being trained.

That is not just a performance choice. The demo on 28 September runs inference
and optimisation only — a test in the demo pack fails the build if any model
training appears in the API layer — so what the panel sees is the same artifact
we measured, every time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pyshared.logging import get_logger

from supplyguard.config import (
    DATA_PROCESSED,
    MODELS_DIR,
    PLANNING_HORIZON_WEEKS,
    RAW_PROCUREMENT_KPI,
    RAW_SAP_DIR,
    RAW_SCMS,
    RAW_SUPPLIER_LINES,
    SEED,
    TARGET_SUPPLIER_COUNT,
    TOP_PLANTS,
)
from supplyguard.etl.asl import build_asl, ensure_coverage
from supplyguard.etl.offers import build_offers
from supplyguard.etl.plants import derive_plants
from supplyguard.etl.procurement_files import load_disruption_orders, load_quality_orders
from supplyguard.etl.requirements import build_plan
from supplyguard.etl.scms import load_scms
from supplyguard.etl.suppliers import build_catalogue
from supplyguard.etl.synthesize import expand_suppliers
from supplyguard.features.build import build_order_features
from supplyguard.risk.base import TrainedModel
from supplyguard.risk.delay import train as train_delay
from supplyguard.risk.disruption import train as train_disruption
from supplyguard.risk.quality import train as train_quality

log = get_logger(__name__)

_CACHE_VERSION = "1"
_TABLES = ("orders", "suppliers", "plants", "requirements", "asl", "offers", "risk")


@dataclass
class PlanningContext:
    """Everything the API serves, held in memory."""

    orders: pd.DataFrame
    suppliers: pd.DataFrame
    plants: pd.DataFrame
    requirements: pd.DataFrame
    asl: pd.DataFrame
    offers: pd.DataFrame
    risk: pd.DataFrame
    metrics: dict[str, dict]

    def summary(self) -> dict[str, int | float]:
        return {
            "purchase_orders": int(len(self.orders)),
            "suppliers": int(len(self.suppliers)),
            "suppliers_real": int((self.suppliers["origin"] == "real").sum()),
            "suppliers_synthetic": int((self.suppliers["origin"] == "synthetic").sum()),
            "plants": int(len(self.plants)),
            "materials": int(self.requirements["material_id"].nunique()),
            "requirement_lines": int(len(self.requirements)),
            "approvals": int(len(self.asl)),
            "offers": int(len(self.offers)),
            "requirement_units": float(self.requirements["required_qty"].sum()),
        }


def _cache_paths() -> dict[str, Path]:
    root = DATA_PROCESSED / f"pr1-v{_CACHE_VERSION}"
    return {name: root / f"{name}.parquet" for name in _TABLES} | {
        "metrics": root / "metrics.json"
    }


def _risk_table(
    orders: pd.DataFrame,
    suppliers: pd.DataFrame,
    delay_model: TrainedModel,
    quality_rate: float,
) -> pd.DataFrame:
    """One risk profile per supplier, ready for the optimiser.

    A supplier's delay probability is the average the model gives its orders.
    Suppliers with no trading history — generated ones, and the ERP catalogue —
    inherit the population average, which is stated rather than hidden: we have
    no evidence about them.
    """
    features = build_order_features(orders)
    features["delay_probability"] = delay_model.predict_proba(features)

    measured = (
        features.groupby("supplier_id")["delay_probability"].mean().reset_index()
    )
    population = float(measured["delay_probability"].mean())

    risk = suppliers[["supplier_id", "origin"]].merge(measured, on="supplier_id", how="left")
    risk["has_measured_risk"] = risk["delay_probability"].notna()
    risk["delay_probability"] = risk["delay_probability"].fillna(population)
    risk["quality_probability"] = quality_rate
    return risk


def build(force: bool = False) -> PlanningContext:
    """Build every table and train the models. Slow, and run once."""
    paths = _cache_paths()
    if not force and all(path.exists() for path in paths.values()):
        return load()

    log.info("building the PR1 planning context from raw data")

    orders = load_scms(RAW_SCMS)
    catalogue = build_catalogue(orders, sap_dir=RAW_SAP_DIR)
    suppliers = expand_suppliers(
        catalogue, orders, target_total=TARGET_SUPPLIER_COUNT, seed=SEED
    )
    plants = derive_plants(orders, top_n=TOP_PLANTS)
    requirements = build_plan(orders, plants, horizon_weeks=PLANNING_HORIZON_WEEKS)

    asl = build_asl(orders, suppliers, plants, requirements=requirements, seed=SEED)
    asl, offers = ensure_coverage(
        orders, suppliers, plants, requirements, asl, build_offers, seed=SEED
    )
    offers = offers.merge(
        suppliers[["supplier_id", "contract_min_share", "contract_max_share", "country"]],
        on="supplier_id",
        how="left",
    )

    log.info("training the risk models")
    features = build_order_features(orders)
    delay_model = train_delay(features)
    quality_model = train_quality(load_quality_orders(RAW_SUPPLIER_LINES))
    disruption_model = train_disruption(load_disruption_orders(RAW_PROCUREMENT_KPI))

    quality_rate = float(quality_model.metrics.get("positives", 0)) / max(
        float(quality_model.metrics.get("rows", 1)), 1.0
    )
    risk = _risk_table(orders, suppliers, delay_model, quality_rate)

    metrics = {
        "delay": _clean_metrics(delay_model),
        "quality": _clean_metrics(quality_model),
        "disruption": _clean_metrics(disruption_model),
    }

    context = PlanningContext(
        orders=orders, suppliers=suppliers, plants=plants, requirements=requirements,
        asl=asl, offers=offers, risk=risk, metrics=metrics,
    )
    _save(context, delay_model, quality_model, disruption_model)
    return context


def _clean_metrics(model: TrainedModel) -> dict:
    """Metrics as plain JSON, with the model's own candidates alongside."""
    out = {
        key: (value if isinstance(value, str | bool) else round(float(value), 4))
        for key, value in model.metrics.items()
    }
    out["candidates"] = {
        name: {k: round(float(v), 4) for k, v in scores.items()}
        for name, scores in model.candidates.items()
    }
    out["feature_importance"] = dict(list(model.feature_importance.items())[:10])
    return out


def _save(
    context: PlanningContext,
    delay_model: TrainedModel,
    quality_model: TrainedModel,
    disruption_model: TrainedModel,
) -> None:
    paths = _cache_paths()
    paths["orders"].parent.mkdir(parents=True, exist_ok=True)

    for name in _TABLES:
        getattr(context, name).to_parquet(paths[name], index=False)
    paths["metrics"].write_text(json.dumps(context.metrics, indent=2), encoding="utf-8")

    for name, model in (
        ("delay", delay_model), ("quality", quality_model), ("disruption", disruption_model)
    ):
        model.save(MODELS_DIR / f"{name}.joblib")

    log.info("planning context cached to %s", paths["orders"].parent)


def load() -> PlanningContext:
    """Load the cached context. Fast, and what the API uses."""
    paths = _cache_paths()
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"planning cache is incomplete (missing {missing}). "
            "Build it with: python -m supplyguard.pipeline"
        )

    tables = {name: pd.read_parquet(paths[name]) for name in _TABLES}
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    return PlanningContext(**tables, metrics=metrics)


def load_model(name: str) -> TrainedModel:
    return TrainedModel.load(MODELS_DIR / f"{name}.joblib")


if __name__ == "__main__":
    context = build(force=True)
    for key, value in context.summary().items():
        print(f"{key:24} {value:,}")
