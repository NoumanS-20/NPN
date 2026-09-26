"""P2 API contract tests, run against the real cached planning context."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from trendwear.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_a_loaded_context(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["loaded"] is True


def test_summary_counts_the_catalogue(client: TestClient) -> None:
    body = client.get("/api/summary").json()
    assert body["styles"] == body["styles_real"] + body["styles_generated"]
    assert body["styles_real"] == 20
    assert body["horizon_weeks"] == 13


def test_styles_can_be_filtered_to_the_real_ones(client: TestClient) -> None:
    body = client.get("/api/styles", params={"origin": "real"}).json()
    assert body["total"] == 20
    assert all(row["origin"] == "real" for row in body["rows"])


def test_every_style_row_declares_its_origin(client: TestClient) -> None:
    rows = client.get("/api/styles", params={"limit": 100}).json()["rows"]
    assert all(row["origin"] in {"real", "synthetic"} for row in rows)


def test_forecast_covers_the_horizon(client: TestClient) -> None:
    body = client.get("/api/forecast").json()
    assert len(body["by_week"]) == 13
    assert body["metrics"]["wape"] < body["metrics"]["wape_seasonal_naive"]


def test_an_unknown_style_forecast_is_404(client: TestClient) -> None:
    assert client.get("/api/forecast", params={"style_id": "NOPE"}).status_code == 404


def test_reconciliation_shows_three_plans(client: TestClient) -> None:
    body = client.get("/api/reconciliation").json()
    week = body["by_week"][0]
    assert {"merch_units", "forecast_units", "supply_units", "consensus_units"} <= set(week)
    assert body["summary"]["gap_value"] >= 0


def test_the_consensus_can_be_agreed_but_not_inflated(client: TestClient) -> None:
    """Pre-S&OP may commit to less than supply allows; it may not promise more."""
    row = client.get("/api/reconciliation").json()["rows"][0]
    supply = row["supply_units"]

    lowered = client.post(
        "/api/reconciliation/consensus",
        params={"style_id": row["style_id"], "week": row["week"], "units": supply / 2},
    ).json()
    assert lowered["consensus_units"] == pytest.approx(supply / 2, rel=0.01)

    raised = client.post(
        "/api/reconciliation/consensus",
        params={"style_id": row["style_id"], "week": row["week"], "units": supply * 10},
    ).json()
    assert raised["consensus_units"] <= supply + 0.01
    assert "capped" in raised["consensus_source"]


def test_an_unknown_consensus_row_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/reconciliation/consensus", params={"style_id": "NOPE", "week": 1, "units": 10}
    )
    assert response.status_code == 404


def test_inventory_reports_flags_and_the_backtest(client: TestClient) -> None:
    body = client.get("/api/inventory").json()
    assert {"stockout_risk", "below_reorder", "healthy", "overstock"} <= set(body["summary"])
    assert 0 <= body["backtest"]["implied_service_level"] <= 1


def test_inventory_can_be_filtered_to_a_flag(client: TestClient) -> None:
    body = client.get("/api/inventory", params={"flag": "stockout_risk"}).json()
    assert all(row["flag"] == "stockout_risk" for row in body["rows"])


def test_production_reports_capacity_and_shortfalls(client: TestClient) -> None:
    body = client.get("/api/production").json()
    assert body["summary"]["units_planned"] > 0
    assert 0 <= body["summary"]["peak_utilisation"] <= 1.001
    assert len(body["capacity_use"]) > 0


def test_fabric_orders_respect_the_lead_time(client: TestClient) -> None:
    body = client.get("/api/fabric").json()
    assert body["summary"]["orders"] > 0
    for order in body["orders"]:
        assert order["arrival_week"] > order["order_week"]


def test_logistics_reports_transit_and_cost(client: TestClient) -> None:
    body = client.get("/api/logistics").json()
    assert body["summary"]["distribution_cost"] > 0
    assert len(body["lanes"]) == 5


def test_markdown_declares_where_its_elasticity_came_from(client: TestClient) -> None:
    """On this dataset the price response is not measurable, and the API says so."""
    body = client.get("/api/markdown").json()
    assert body["elasticity"]["source"] in {"measured", "assumed"}
    assert body["elasticity"]["reason"]
    assert body["summary"]["styles"] > 0


def test_markdown_can_be_filtered_to_recommendations(client: TestClient) -> None:
    body = client.get("/api/markdown", params={"recommend_only": True}).json()
    assert all(row["recommend"] for row in body["rows"])


def test_financials_cover_demand_supply_and_money(client: TestClient) -> None:
    body = client.get("/api/financials").json()
    assert {"revenue", "gross_margin", "inventory_value", "distribution_cost"} <= set(
        body["totals"]
    )
    assert len(body["by_category"]) > 0


def test_the_cycle_has_four_stages_and_stored_versions(client: TestClient) -> None:
    body = client.get("/api/cycles").json()
    assert [stage["key"] for stage in body["stages"]] == [
        "demand_review", "supply_review", "pre_sop", "executive_approval"
    ]
    assert body["cycles"] >= 3
    assert len(body["versions"]) >= 12


def test_kpis_carry_the_cockpit_numbers(client: TestClient) -> None:
    body = client.get("/api/kpis").json()
    for key in ("revenue", "gap_value", "forecast_wape", "styles_at_stockout_risk"):
        assert key in body
    assert body["forecast_wape"] < body["forecast_wape_seasonal_naive"]


def test_model_metrics_include_the_cold_start_and_the_elasticity(client: TestClient) -> None:
    body = client.get("/api/models/metrics").json()
    assert body["forecast"]["scored_on"] == "real styles only"
    assert body["cold_start"]["scored"] is True
    assert body["elasticity"]["source"] in {"measured", "assumed"}
