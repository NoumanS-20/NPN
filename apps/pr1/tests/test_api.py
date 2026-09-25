"""API contract tests.

The screens and, in a production deployment, an ERP both talk to this layer, so
the shapes here are a contract. These tests run against the real cached planning
context — if the API says a plan meets demand, it really does.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from supplyguard.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --- the basics ----------------------------------------------------------


def test_health_reports_a_loaded_context(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["loaded"] is True


def test_summary_counts_match_the_pipeline(client: TestClient) -> None:
    body = client.get("/api/summary").json()
    assert body["suppliers"] == body["suppliers_real"] + body["suppliers_synthetic"]
    assert body["suppliers_real"] == 217
    assert body["plants"] == 8


# --- the comparison table ------------------------------------------------


def test_suppliers_paginate(client: TestClient) -> None:
    body = client.get("/api/suppliers?limit=25").json()
    assert body["total"] == 520
    assert len(body["rows"]) == 25


def test_every_supplier_row_declares_its_origin(client: TestClient) -> None:
    """Generated suppliers must be visible as generated, on every screen."""
    rows = client.get("/api/suppliers?limit=200").json()["rows"]
    assert all(row["origin"] in {"real", "synthetic", "public-synthetic"} for row in rows)


def test_suppliers_can_be_filtered_to_a_material(client: TestClient) -> None:
    materials = client.get("/api/materials").json()
    material_id = materials[0]["material_id"]
    body = client.get("/api/suppliers", params={"material_id": material_id}).json()
    assert 0 < body["total"] < 520


def test_suppliers_sort(client: TestClient) -> None:
    rows = client.get("/api/suppliers?sort=avg_lead_days&descending=false&limit=10").json()["rows"]
    leads = [row["avg_lead_days"] for row in rows if row["avg_lead_days"] is not None]
    assert leads == sorted(leads)


def test_unknown_origin_filter_is_rejected(client: TestClient) -> None:
    assert client.get("/api/suppliers?origin=imaginary").status_code == 422


# --- allocation ----------------------------------------------------------


def test_allocate_meets_demand(client: TestClient) -> None:
    plants = client.get("/api/plants").json()
    body = {"plant_id": plants[0]["plant_id"], "weeks": 2}
    result = client.post("/api/allocate", json=body).json()

    assert result["status"] == "optimal"
    requirements = client.get(
        "/api/requirements", params={"plant_id": plants[0]["plant_id"]}
    ).json()
    wanted = sum(r["required_qty"] for r in requirements if r["week"] <= 2)
    assert sum(line["qty"] for line in result["lines"]) == pytest.approx(wanted, rel=0.01)


def test_allocate_reports_its_own_solve_time(client: TestClient) -> None:
    """Shown beside the result on screen — our evidence for real-time decisions."""
    result = client.post("/api/allocate", json={"weeks": 1}).json()
    assert 0 < result["solve_seconds"] < 10


def test_every_allocation_line_carries_a_reason(client: TestClient) -> None:
    result = client.post("/api/allocate", json={"weeks": 1}).json()
    assert result["lines"]
    assert all(len(line["reason"]) > 15 for line in result["lines"])


def test_risk_weight_changes_the_plan(client: TestClient) -> None:
    """The headline behaviour, through the API the screen uses."""
    base = {"weeks": 2, "max_supplier_share": 0.4}
    ignore = client.post(
        "/api/allocate", json={**base, "weights": {"cost": 1, "risk": 0, "quality": 0}}
    ).json()
    price_risk = client.post(
        "/api/allocate", json={**base, "weights": {"cost": 1, "risk": 3, "quality": 1}}
    ).json()

    assert price_risk["expected_late_units"] < ignore["expected_late_units"]
    assert price_risk["high_risk_share"] <= ignore["high_risk_share"]


def test_excluding_a_supplier_removes_it(client: TestClient) -> None:
    first = client.post("/api/allocate", json={"weeks": 1}).json()
    victim = first["lines"][0]["supplier_id"]
    second = client.post(
        "/api/allocate", json={"weeks": 1, "excluded_suppliers": [victim]}
    ).json()
    assert victim not in {line["supplier_id"] for line in second["lines"]}


def test_invalid_weights_are_rejected(client: TestClient) -> None:
    body = {"weeks": 1, "weights": {"cost": -1, "risk": 1, "quality": 1}}
    assert client.post("/api/allocate", json=body).status_code == 422


def test_a_filter_matching_nothing_returns_404(client: TestClient) -> None:
    body = {"material_id": "does-not-exist"}
    assert client.post("/api/allocate", json=body).status_code == 404


def test_compare_returns_the_plan_and_three_baselines(client: TestClient) -> None:
    body = client.post("/api/allocate/compare", json={"weeks": 1}).json()
    assert set(body["baselines"]) == {"cheapest_first", "equal_split", "historical_mix"}
    assert set(body["comparison"]) == set(body["baselines"])
    assert "invoice_delta_pct" in body["comparison"]["historical_mix"]


# --- pre-PO risk check ---------------------------------------------------


def test_score_po_returns_probabilities_and_reasons(client: TestClient) -> None:
    offers = client.get("/api/suppliers?limit=1").json()["rows"][0]
    materials = client.get("/api/materials").json()
    body = {
        "supplier_id": offers["supplier_id"],
        "material_id": materials[0]["material_id"],
        "quantity": 5000,
    }
    result = client.post("/api/risk/score-po", json=body).json()

    assert 0 <= result["delay_probability"] <= 1
    assert 0 <= result["quality_probability"] <= 1
    assert result["verdict"] in {"normal", "elevated", "high"}
    assert len(result["explanation"]) > 40
    assert 1 <= len(result["top_factors"]) <= 4


def test_score_po_rejects_an_unknown_supplier(client: TestClient) -> None:
    body = {"supplier_id": "nobody", "material_id": "x", "quantity": 10}
    assert client.post("/api/risk/score-po", json=body).status_code == 404


# --- scenarios -----------------------------------------------------------


def test_scenarios_are_listed_with_their_parameters(client: TestClient) -> None:
    body = client.get("/api/scenarios").json()
    assert {s["key"] for s in body} == {
        "supplier_outage", "demand_spike", "lead_time_shock", "price_shock"
    }


def test_outage_picks_the_largest_supplier_when_none_is_named(client: TestClient) -> None:
    body = {"parameters": {}, "allocation": {"weeks": 1}}
    result = client.post("/api/scenarios/supplier_outage", json=body).json()
    assert result["parameters"]["supplier_id"]
    assert result["narrative"]
    assert "before" in result and "after" in result


def test_demand_spike_costs_more(client: TestClient) -> None:
    body = {"parameters": {"uplift_pct": 30}, "allocation": {"weeks": 1}}
    result = client.post("/api/scenarios/demand_spike", json=body).json()
    assert result["deltas"]["invoice_pct"] > 20


def test_unknown_scenario_returns_404(client: TestClient) -> None:
    assert client.post("/api/scenarios/earthquake", json={}).status_code == 404


# --- monitoring ----------------------------------------------------------


def test_model_metrics_include_the_models_that_did_not_ship(client: TestClient) -> None:
    body = client.get("/api/models/metrics").json()
    assert body["delay"]["label_sufficient"] is True
    assert body["quality"]["label_sufficient"] is False
    assert body["disruption"]["label_sufficient"] is False
    assert body["quality"]["sufficiency_reason"]


def test_kpis_carry_the_headline_numbers(client: TestClient) -> None:
    body = client.get("/api/kpis").json()
    assert body["vs_historical_invoice_pct"] < 0        # cheaper than the status quo
    assert body["plan_high_risk_share"] >= 0
    assert body["delay_model_roc_auc"] > 0.7
