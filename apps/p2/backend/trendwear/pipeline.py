"""Assemble everything TrendWear Planner needs, once, and cache it.

Same discipline as SupplyGuard: the ETL, the catalogue, the forecast model and
the whole planning chain are built ahead of time and written to disk. The API
loads the cache at startup and serves from memory, so nothing is trained while
the server is up and the demo shows the same artifacts we measured.

The chain runs in the order the mentor's flow lays out, because each step feeds
the next:

    sales -> forecast -> safety stock -> production -> fabric -> distribution
          -> reconciliation -> financials -> S&OP versions
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pyshared.logging import get_logger

from trendwear.config import (
    DATA_PROCESSED,
    FABRIC_LEAD_TIME_WEEKS,
    FORECAST_HORIZON_WEEKS,
    MODELS_DIR,
    RAW_RETAIL,
    ROLLING_CYCLES,
    SEED,
    SERVICE_LEVEL,
    TARGET_STYLE_COUNT,
)
from trendwear.etl.retail import launch_curve, load_weekly_sales
from trendwear.etl.synthesize import build_network, build_style_catalogue, simulate_sales
from trendwear.fabric.lotsize import (
    order_plan,
    requirements_from_production,
    units_supportable,
)
from trendwear.forecast.coldstart import evaluate_holdout
from trendwear.forecast.model import ForecastModel, build_features, forecast_horizon
from trendwear.forecast.model import train as train_forecast
from trendwear.inventory.safety_stock import backtest, build_position, compute
from trendwear.markdown.elasticity import fit, fit_by_category
from trendwear.markdown.recommend import recommend_all
from trendwear.production.plan import build_plan
from trendwear.sop.cycle import advance, run_rolling
from trendwear.sop.distribution import store_availability
from trendwear.sop.financials import roll_up
from trendwear.sop.reconcile import build as build_reconciliation
from trendwear.sop.reconcile import build_merchandising_plan

log = get_logger(__name__)

_CACHE_VERSION = "1"
_TABLES = (
    "sales", "styles", "plants", "stores", "lanes", "fabric_bom", "forecast",
    "safety_stock", "inventory", "production", "capacity_use", "shortfalls",
    "fabric_orders", "availability", "reconciliation", "markdown", "versions",
)


@dataclass
class PlanningContext:
    """Everything the API serves."""

    sales: pd.DataFrame
    styles: pd.DataFrame
    plants: pd.DataFrame
    stores: pd.DataFrame
    lanes: pd.DataFrame
    fabric_bom: pd.DataFrame
    forecast: pd.DataFrame
    safety_stock: pd.DataFrame
    inventory: pd.DataFrame
    production: pd.DataFrame
    capacity_use: pd.DataFrame
    shortfalls: pd.DataFrame
    fabric_orders: pd.DataFrame
    availability: pd.DataFrame
    reconciliation: pd.DataFrame
    markdown: pd.DataFrame
    versions: pd.DataFrame
    metrics: dict

    def summary(self) -> dict[str, float | int]:
        real = self.styles[self.styles["origin"] == "real"]
        return {
            "styles": int(len(self.styles)),
            "styles_real": int(len(real)),
            "styles_generated": int(len(self.styles) - len(real)),
            "weeks_of_history": int(self.sales["week_index"].nunique()),
            "plants": int(len(self.plants)),
            "stores": int(len(self.stores)),
            "fabrics": int(self.fabric_bom["fabric_id"].nunique()),
            "horizon_weeks": FORECAST_HORIZON_WEEKS,
            "forecast_units": round(float(self.forecast["forecast_units"].sum()), 1),
            "production_units": round(float(self.production["units"].sum()), 1)
            if len(self.production) else 0.0,
        }


def _cache_paths() -> dict[str, Path]:
    root = DATA_PROCESSED / f"p2-v{_CACHE_VERSION}"
    return {name: root / f"{name}.parquet" for name in _TABLES} | {
        "metrics": root / "metrics.json"
    }


def build(force: bool = False) -> PlanningContext:
    """Run the whole chain. Slow, and run once."""
    paths = _cache_paths()
    if not force and all(path.exists() for path in paths.values()):
        return load()

    log.info("building the P2 planning context")

    # 1. Sales history, real and generated.
    real_sales = load_weekly_sales(RAW_RETAIL)
    styles = build_style_catalogue(real_sales, n_styles=TARGET_STYLE_COUNT, seed=SEED)
    shape = launch_curve(real_sales)
    generated = simulate_sales(styles, real_sales, shape, seed=SEED)
    sales = pd.concat([real_sales, generated], ignore_index=True)

    network = build_network(styles, seed=SEED)

    # 2. Demand forecast.
    log.info("training the demand forecast")
    model = train_forecast(sales)
    horizons = [
        forecast_horizon(model, sales, style_id, horizon=FORECAST_HORIZON_WEEKS)
        for style_id in sales["style_id"].unique()
    ]
    forecast = pd.concat(horizons, ignore_index=True)
    forecast["week"] = forecast.groupby("style_id").cumcount() + 1

    cold_start = evaluate_holdout(styles, real_sales, shape, seed=SEED)

    # 3. Safety stock from the model's own residuals.
    featured = build_features(sales).dropna(subset=["lag_1"])
    featured["prediction"] = model.predict(featured)
    residuals = featured.assign(error=featured["units"] - featured["prediction"])[
        ["style_id", "error"]
    ]
    safety = compute(residuals, FABRIC_LEAD_TIME_WEEKS, SERVICE_LEVEL)
    inventory = build_position(sales, safety, forecast.rename(columns={"week": "_w"}))
    safety_check = backtest(sales, safety)

    # 4. Production against capacity, then fabric, then production again with
    #    fabric as a constraint — the second pass is what makes the lead time
    #    bite rather than being a number in a table.
    demand = forecast.rename(columns={"forecast_units": "units"})[["style_id", "week", "units"]]
    first_pass = build_plan(demand, styles, network["plants"], safety_stock=safety)

    requirements = requirements_from_production(first_pass.lines, network["fabric_bom"])
    moq = network["fabric_bom"].set_index("fabric_id")["fabric_moq_metres"].to_dict()
    price = network["fabric_bom"].set_index("fabric_id")["fabric_price"].to_dict()
    orders = order_plan(requirements, moq=moq, price=price, lead_time_weeks=FABRIC_LEAD_TIME_WEEKS)

    weeks = sorted(demand["week"].unique())
    supportable = units_supportable(orders, network["fabric_bom"], weeks)
    production = build_plan(
        demand, styles, network["plants"], safety_stock=safety, fabric_available=supportable
    )

    # 5. Distribution, reconciliation, markdown, money.
    availability = store_availability(production.lines, network["lanes"], network["stores"])

    supply = (
        production.lines.groupby(["style_id", "week"], as_index=False)["units"].sum()
        .rename(columns={"units": "supply_units"})
        if len(production.lines)
        else pd.DataFrame(columns=["style_id", "week", "supply_units"])
    )
    merch = build_merchandising_plan(forecast, styles, seed=SEED)
    reconciliation = build_reconciliation(merch, forecast, supply, styles)

    elasticities = fit_by_category(real_sales, styles)
    default_elasticity = fit(real_sales)
    markdown = recommend_all(styles, sales, elasticities, default_elasticity)

    financials = roll_up(
        reconciliation, styles, production=production, inventory=inventory,
        lanes=network["lanes"],
    )

    # 6. The rolling cycle, with a version stored at every stage.
    cycles = run_rolling(months=ROLLING_CYCLES, horizon_weeks=FORECAST_HORIZON_WEEKS)
    for index, cycle in enumerate(cycles):
        scale = 1 - index * 0.04          # later cycles plan a little tighter
        for _ in range(4):
            advance(cycle, {key: value * scale for key, value in financials.items()})

    from trendwear.sop.cycle import history

    metrics = {
        "forecast": {k: (v if isinstance(v, str | bool) else round(float(v), 4))
                     for k, v in model.metrics.items()},
        "forecast_importance": dict(list(model.feature_importance.items())[:10]),
        "cold_start": cold_start,
        "safety_stock": safety_check,
        "financials": financials,
        "production": {
            "status": production.status,
            "lost_sales_units": production.lost_sales_units,
            "lost_sales_value": production.lost_sales_value,
            "solve_seconds": production.solve_seconds,
        },
        "elasticity": {
            "value": default_elasticity.value,
            "source": default_elasticity.source,
            "r_squared": default_elasticity.r_squared,
            "reason": default_elasticity.reason,
        },
    }

    context = PlanningContext(
        sales=sales, styles=styles, plants=network["plants"], stores=network["stores"],
        lanes=network["lanes"], fabric_bom=network["fabric_bom"], forecast=forecast,
        safety_stock=safety, inventory=inventory, production=production.lines,
        capacity_use=production.capacity_use, shortfalls=production.shortfalls,
        fabric_orders=pd.DataFrame([order.__dict__ for order in orders]),
        availability=availability, reconciliation=reconciliation, markdown=markdown,
        versions=history(cycles), metrics=metrics,
    )

    _save(context, model)
    return context


def _save(context: PlanningContext, model: ForecastModel) -> None:
    paths = _cache_paths()
    paths["sales"].parent.mkdir(parents=True, exist_ok=True)

    for name in _TABLES:
        frame = getattr(context, name)
        if name == "fabric_orders" and len(frame):
            frame = frame.assign(covers_weeks=frame["covers_weeks"].astype(str))
        frame.to_parquet(paths[name], index=False)

    paths["metrics"].write_text(
        json.dumps(context.metrics, indent=2, default=str), encoding="utf-8"
    )
    model.save(MODELS_DIR / "demand.joblib")
    log.info("planning context cached to %s", paths["sales"].parent)


def load() -> PlanningContext:
    paths = _cache_paths()
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"planning cache is incomplete (missing {missing}). "
            "Build it with: python -m trendwear.pipeline"
        )

    tables = {name: pd.read_parquet(paths[name]) for name in _TABLES}
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    return PlanningContext(**tables, metrics=metrics)


if __name__ == "__main__":
    context = build(force=True)
    for key, value in context.summary().items():
        print(f"{key:24} {value:,}")
