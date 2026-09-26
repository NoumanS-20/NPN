"""HTTP endpoints for TrendWear Planner.

Everything the screens need, and the integration point a production deployment
would attach to. The planning context is loaded once at startup; nothing here
trains a model or re-runs the chain.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from trendwear.api.state import state
from trendwear.sop.cycle import STAGE_LABELS, STAGES
from trendwear.sop.financials import by_category
from trendwear.sop.reconcile import biggest_gaps, override_consensus

router = APIRouter(prefix="/api")


def _records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    out = frame.head(limit) if limit else frame
    return out.where(pd.notna(out), None).to_dict("records")


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "app": "TrendWear Planner", "loaded": state.is_loaded}


@router.get("/summary")
def summary() -> dict[str, Any]:
    return state.context.summary()


@router.get("/styles")
def styles(
    origin: str | None = Query(None, pattern="^(real|synthetic)$"),
    category: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    rows = state.styles_view()
    if origin:
        rows = rows[rows["origin"] == origin]
    if category:
        rows = rows[rows["category"] == category]
    return {"total": int(len(rows)), "rows": _records(rows, limit)}


@router.get("/forecast")
def forecast(style_id: str | None = None) -> dict[str, Any]:
    rows = state.context.forecast
    if style_id:
        rows = rows[rows["style_id"] == style_id]
        if rows.empty:
            raise HTTPException(404, f"No forecast for style {style_id!r}.")

    weekly = (
        state.context.forecast.groupby("week", as_index=False)["forecast_units"].sum()
        if style_id is None
        else rows[["week", "forecast_units"]]
    )
    return {
        "rows": _records(rows, 500),
        "by_week": _records(weekly),
        "metrics": state.context.metrics["forecast"],
        "cold_start": state.context.metrics["cold_start"],
    }


@router.get("/reconciliation")
def reconciliation(style_id: str | None = None) -> dict[str, Any]:
    rows = state.context.reconciliation
    if style_id:
        rows = rows[rows["style_id"] == style_id]

    by_week = rows.groupby("week", as_index=False).agg(
        merch_units=("merch_units", "sum"),
        forecast_units=("forecast_units", "sum"),
        supply_units=("supply_units", "sum"),
        consensus_units=("consensus_units", "sum"),
    )

    return {
        "summary": state.reconciliation_summary(),
        "by_week": _records(by_week),
        "biggest_gaps": _records(biggest_gaps(rows, state.context.styles)),
        "rows": _records(rows, 400),
    }


@router.post("/reconciliation/consensus")
def set_consensus(style_id: str, week: int, units: float) -> dict[str, Any]:
    """Agree a number by hand, as Pre-S&OP would. Capped at what supply allows."""
    try:
        updated = override_consensus(state.context.reconciliation, style_id, week, units)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error

    state.set_reconciliation(updated)
    row = updated[(updated["style_id"] == style_id) & (updated["week"] == week)].iloc[0]
    return {
        "style_id": style_id,
        "week": week,
        "consensus_units": float(row["consensus_units"]),
        "consensus_source": str(row["consensus_source"]),
        "supply_units": float(row["supply_units"]),
    }


@router.get("/inventory")
def inventory(flag: str | None = None) -> dict[str, Any]:
    rows = state.context.inventory
    if flag:
        rows = rows[rows["flag"] == flag]
    return {
        "summary": state.inventory_summary(),
        "backtest": state.context.metrics["safety_stock"],
        "rows": _records(rows, 200),
    }


@router.get("/production")
def production() -> dict[str, Any]:
    context = state.context
    return {
        "summary": state.production_summary(),
        "capacity_use": _records(context.capacity_use),
        "shortfalls": _records(context.shortfalls, 100),
        "lines": _records(context.production, 300),
    }


@router.get("/fabric")
def fabric() -> dict[str, Any]:
    return {
        "summary": state.fabric_summary(),
        "orders": _records(state.context.fabric_orders, 100),
        "bom": _records(state.context.fabric_bom, 100),
    }


@router.get("/logistics")
def logistics() -> dict[str, Any]:
    context = state.context
    by_store = (
        context.availability.groupby(["store_id", "week_available"], as_index=False)
        .agg(units=("units", "sum"), cost=("distribution_cost", "sum"))
        if len(context.availability)
        else pd.DataFrame()
    )
    return {
        "summary": state.logistics_summary(),
        "lanes": _records(context.lanes),
        "by_store": _records(by_store, 200),
    }


@router.get("/markdown")
def markdown(recommend_only: bool = False) -> dict[str, Any]:
    rows = state.context.markdown
    if recommend_only:
        rows = rows[rows["recommend"]]
    return {
        "summary": state.markdown_summary(),
        "elasticity": state.context.metrics["elasticity"],
        "rows": _records(rows, 200),
    }


@router.get("/financials")
def financials() -> dict[str, Any]:
    return {
        "totals": state.context.metrics["financials"],
        "by_category": _records(by_category(state.context.reconciliation, state.context.styles)),
    }


@router.get("/cycles")
def cycles() -> dict[str, Any]:
    versions = state.context.versions
    return {
        "stages": [{"key": key, "label": STAGE_LABELS[key]} for key in STAGES],
        "versions": _records(versions),
        "current_stage": str(versions.iloc[-1]["stage"]) if len(versions) else STAGES[0],
        "cycles": int(versions["cycle_month"].nunique()) if len(versions) else 0,
    }


@router.get("/kpis")
def kpis() -> dict[str, Any]:
    return state.kpis()


@router.get("/models/metrics")
def model_metrics() -> dict[str, Any]:
    return {
        "forecast": state.context.metrics["forecast"],
        "feature_importance": state.context.metrics["forecast_importance"],
        "cold_start": state.context.metrics["cold_start"],
        "safety_stock": state.context.metrics["safety_stock"],
        "elasticity": state.context.metrics["elasticity"],
    }
