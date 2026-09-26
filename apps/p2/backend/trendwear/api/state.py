"""Application state for TrendWear Planner.

The planning context is loaded once and held in memory. Requests read it. The one
thing a request may change is the consensus number, because agreeing that is what
the Pre-S&OP stage is for.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
from pyshared.logging import get_logger

from trendwear import pipeline
from trendwear.inventory.safety_stock import summarise as inventory_summarise
from trendwear.sop.distribution import summarise as logistics_summarise
from trendwear.sop.reconcile import summarise as reconcile_summarise

log = get_logger(__name__)


class State:
    def __init__(self) -> None:
        self._context: pipeline.PlanningContext | None = None

    @property
    def is_loaded(self) -> bool:
        return self._context is not None

    @property
    def context(self) -> pipeline.PlanningContext:
        if self._context is None:
            raise RuntimeError("planning context is not loaded; call state.load() at startup")
        return self._context

    def load(self, build_if_missing: bool = True) -> None:
        try:
            self._context = pipeline.load()
            log.info("planning context loaded from cache")
        except FileNotFoundError:
            if not build_if_missing:
                raise
            log.warning("no cached planning context; building it now (this takes a few minutes)")
            self._context = pipeline.build(force=True)

    def warm(self) -> None:
        """Compute the summaries once, at startup rather than on first click."""
        self.styles_view()
        self.kpis()

    def set_reconciliation(self, reconciliation: pd.DataFrame) -> None:
        """Record an agreed consensus number and invalidate what depends on it."""
        self.context.reconciliation = reconciliation
        self.kpis.cache_clear()

    @lru_cache(maxsize=1)  # noqa: B019 - one cache for the life of the process
    def styles_view(self) -> pd.DataFrame:
        """The style list with its planning numbers attached."""
        styles = self.context.styles
        forecast = self.context.forecast.groupby("style_id", as_index=False)["forecast_units"].sum()
        inventory = self.context.inventory[["style_id", "on_hand", "weeks_of_cover", "flag"]]
        markdown = self.context.markdown[["style_id", "recommend", "depth_pct", "week"]].rename(
            columns={"recommend": "markdown_recommended", "week": "markdown_week"}
        )

        merged = (
            styles.merge(forecast, on="style_id", how="left")
            .merge(inventory, on="style_id", how="left")
            .merge(markdown, on="style_id", how="left")
        )
        return merged

    def reconciliation_summary(self) -> dict:
        return reconcile_summarise(self.context.reconciliation)

    def inventory_summary(self) -> dict:
        return inventory_summarise(self.context.inventory)

    def production_summary(self) -> dict:
        use = self.context.capacity_use
        lines = self.context.production
        shortfalls = self.context.shortfalls
        return {
            "units_planned": round(float(lines["units"].sum()), 1) if len(lines) else 0.0,
            "styles": int(lines["style_id"].nunique()) if len(lines) else 0,
            "peak_utilisation": round(float(use["utilisation"].max()), 4) if len(use) else 0.0,
            "mean_utilisation": round(float(use["utilisation"].mean()), 4) if len(use) else 0.0,
            "weeks_at_capacity": int((use["utilisation"] > 0.98).sum()) if len(use) else 0,
            "shortfall_units": round(float(shortfalls["units_short"].sum()), 1)
            if len(shortfalls) else 0.0,
            "shortfall_value": round(float(shortfalls["margin_lost"].sum()), 2)
            if len(shortfalls) else 0.0,
        }

    def fabric_summary(self) -> dict:
        orders = self.context.fabric_orders
        if orders.empty:
            return {"orders": 0, "metres": 0.0, "cost": 0.0}
        return {
            "orders": int(len(orders)),
            "fabrics": int(orders["fabric_id"].nunique()),
            "metres": round(float(orders["metres"].sum()), 1),
            "cost": round(float(orders["cost"].sum()), 2),
            "orders_already_due": int((orders["order_week"] < 0).sum()),
            "earliest_order_week": int(orders["order_week"].min()),
        }

    def logistics_summary(self) -> dict:
        return logistics_summarise(self.context.availability)

    @lru_cache(maxsize=1)  # noqa: B019 - invalidated when the consensus changes
    def kpis(self) -> dict:
        """The headline numbers for the cockpit."""
        context = self.context
        reconciliation = self.reconciliation_summary()
        inventory = self.inventory_summary()
        production = self.production_summary()
        financials = context.metrics["financials"]
        forecast = context.metrics["forecast"]
        markdown = self.markdown_summary()

        return {
            "consensus_units": reconciliation["consensus_units"],
            "gap_units": reconciliation["gap_units"],
            "gap_value": reconciliation["gap_value"],
            "ambition_vs_forecast_pct": reconciliation["ambition_vs_forecast_pct"],
            "revenue": financials["revenue"],
            "gross_margin": financials["gross_margin"],
            "margin_pct": financials["margin_pct"],
            "inventory_value": financials["inventory_value"],
            "distribution_cost": financials["distribution_cost"],
            "forecast_wape": round(float(forecast["wape"]), 4),
            "forecast_wape_seasonal_naive": round(float(forecast["wape_seasonal_naive"]), 4),
            "styles_at_stockout_risk": inventory["stockout_risk"],
            "styles_below_reorder": inventory["below_reorder"],
            "peak_utilisation": production["peak_utilisation"],
            "shortfall_units": production["shortfall_units"],
            "styles_marked_down": markdown["marked_down"],
            "margin_recovered": markdown.get("margin_recovered", 0.0),
        }

    def markdown_summary(self) -> dict:
        from trendwear.markdown.recommend import summarise

        return summarise(self.context.markdown)


state = State()
