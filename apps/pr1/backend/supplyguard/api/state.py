"""Application state: the planning context, loaded once.

The context is a few hundred thousand rows, so it is loaded at startup and held
in memory. Requests read it; nothing mutates it. Scenarios work on copies, which
is why a scenario run cannot leak into the next request.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
from pyshared.logging import get_logger

from supplyguard import pipeline
from supplyguard.optimizer.baselines import compare, run_all
from supplyguard.optimizer.model import solve
from supplyguard.optimizer.types import AllocationRequest, Requirement, Weights

log = get_logger(__name__)


class State:
    """Holds the planning context for the life of the process."""

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

    def warm(self) -> None:
        """Compute the expensive views once, at startup rather than on first click."""
        self.suppliers_view()
        self.kpis()

    def load(self, build_if_missing: bool = True) -> None:
        try:
            self._context = pipeline.load()
            log.info("planning context loaded from cache")
        except FileNotFoundError:
            if not build_if_missing:
                raise
            log.warning("no cached planning context; building it now (this takes a minute)")
            self._context = pipeline.build(force=True)

    def set_context(self, context: pipeline.PlanningContext) -> None:
        """Used by tests to inject a small context."""
        self._context = context
        self.suppliers_view.cache_clear()
        self.kpis.cache_clear()

    @lru_cache(maxsize=1)  # noqa: B019 - one cache for the life of the process
    def suppliers_view(self) -> pd.DataFrame:
        """The supplier table as the comparison screen wants it."""
        suppliers = self.context.suppliers
        risk = self.context.risk[
            ["supplier_id", "delay_probability", "quality_probability", "has_measured_risk"]
        ]
        merged = suppliers.merge(risk, on="supplier_id", how="left")

        columns = [
            "supplier_id", "name", "country", "product_group", "origin", "orders",
            "on_time_rate", "avg_lead_days", "p75_lead_days", "lead_days_source",
            "avg_unit_price", "historical_volume", "moq", "capacity_per_week",
            "contract_min_share", "contract_max_share", "delay_probability",
            "quality_probability", "has_measured_risk",
        ]
        return merged[[c for c in columns if c in merged.columns]]

    def risk_for(self, supplier_id: str) -> pd.Series | None:
        rows = self.context.risk[self.context.risk["supplier_id"] == supplier_id]
        return rows.iloc[0] if len(rows) else None

    @lru_cache(maxsize=1)  # noqa: B019 - the context never changes while the app runs
    def kpis(self) -> dict[str, float | int | str]:
        """Headline numbers: our plan against the status quo.

        Cached, because computing it means solving the full plan and all three
        baselines — about ten seconds. The context is immutable for the life of
        the process, so the answer cannot go stale, and the overview page loads
        instantly after the first call rather than making a panel wait.
        """
        plan_requirements = [
            Requirement(r.material_id, r.plant_id, int(r.week), float(r.required_qty))
            for r in self.context.requirements.itertuples()
        ]
        request = AllocationRequest(requirements=plan_requirements, weights=Weights(1, 1, 1))

        plan = solve(request, self.context.offers, self.context.risk)
        baselines = run_all(request, self.context.offers, self.context.orders, self.context.risk)
        deltas = compare(plan, baselines)

        historical = deltas.get("historical_mix", {})
        return {
            "plan_total_cost": plan.total_cost,
            "plan_invoice": plan.material_cost,
            "plan_expected_late_units": plan.expected_late_units,
            "plan_high_risk_share": plan.high_risk_share,
            "suppliers_used": plan.suppliers_used,
            "solve_seconds": plan.solve_seconds,
            "vs_historical_invoice_pct": historical.get("invoice_delta_pct", 0.0),
            "vs_historical_total_cost_pct": historical.get("total_cost_delta_pct", 0.0),
            "vs_historical_expected_late_pct": historical.get("expected_late_delta_pct", 0.0),
            "vs_cheapest_invoice_pct": deltas.get("cheapest_first", {}).get(
                "invoice_delta_pct", 0.0
            ),
            "vs_cheapest_high_risk_pp": deltas.get("cheapest_first", {}).get(
                "high_risk_delta_pp", 0.0
            ),
            "delay_model": self.context.metrics["delay"]["model"],
            "delay_model_roc_auc": self.context.metrics["delay"]["roc_auc"],
        }


state = State()
