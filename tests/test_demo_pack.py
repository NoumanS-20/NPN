"""The demo pack: pre-trained artifacts, frozen seeds, preloaded scenarios.

The evaluation is a live demo, so these guard the things that would ruin it:
a model training while a judge waits, a plan that differs from the rehearsal, or
an artifact that is missing on the day.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_no_model_is_trained_inside_an_api_module() -> None:
    """The decisive rule: the demo runs inference and optimisation only."""
    api_files = list((ROOT / "apps").rglob("*/api/*.py"))
    assert api_files, "no API modules found to check"

    for path in api_files:
        text = path.read_text(encoding="utf-8")
        for token in (".fit(", "train(", "LGBMRegressor", "XGBClassifier"):
            assert token not in text, f"{path.name} appears to train a model ({token})"


def test_every_seed_is_pinned_in_one_place_per_application() -> None:
    for config in ("apps/pr1/backend/supplyguard/config.py",
                   "apps/p2/backend/trendwear/config.py"):
        text = (ROOT / config).read_text(encoding="utf-8")
        assert "SEED = 42" in text, f"{config} does not pin a seed"


def test_the_demo_pack_script_declares_every_artifact() -> None:
    from scripts.build_demo_pack import EXPECTED

    assert len(EXPECTED) >= 6
    for name, path in EXPECTED.items():
        assert path.startswith(("data/processed/", "models/")), f"{name} is outside the pack"


@pytest.mark.requires_data
def test_the_demo_pack_is_built_and_loadable() -> None:
    """Fails loudly if an artifact is missing from a checkout that should have them."""
    from scripts.build_demo_pack import verify

    result = verify()
    assert result["missing"] == [], f"missing artifacts: {result['missing']}"
    assert result["ready"] is True


def test_each_application_preloads_a_baseline_and_a_disruption() -> None:
    from supplyguard.demo.scenarios import PRELOADED as pr1
    from trendwear.demo.scenarios import PRELOADED as p2

    assert {"baseline", "price_only", "disruption"} <= set(pr1)
    assert "baseline" in p2 and len(p2) >= 2


def test_every_demo_scenario_carries_the_line_to_say() -> None:
    """A demo where someone improvises the explanation is a demo that rambles."""
    from supplyguard.demo.scenarios import PRELOADED as pr1
    from trendwear.demo.scenarios import PRELOADED as p2

    for scenarios in (pr1, p2):
        for scenario in scenarios.values():
            assert len(scenario.say_this) > 80, f"{scenario.key} has no script"
            assert scenario.description


@pytest.mark.requires_data
def test_the_same_scenario_produces_the_same_plan_twice() -> None:
    """A rehearsed number must be the number the panel sees."""
    from supplyguard.demo.scenarios import PRELOADED, to_request
    from supplyguard.optimizer.model import solve
    from supplyguard.optimizer.types import Requirement
    from supplyguard.pipeline import load

    context = load()
    plan_rows = context.requirements[
        (context.requirements["plant_id"] == "plant-nigeria")
        & (context.requirements["week"] <= 2)
    ]
    requirements = [
        Requirement(row.material_id, row.plant_id, int(row.week), float(row.required_qty))
        for row in plan_rows.itertuples()
    ]

    request = to_request(PRELOADED["baseline"], requirements)
    first = solve(request, context.offers, context.risk)
    second = solve(request, context.offers, context.risk)

    assert first.total_cost == second.total_cost
    assert [line.qty for line in first.lines] == [line.qty for line in second.lines]

@pytest.mark.requires_data
def test_a_panel_can_change_an_input_without_anything_retraining() -> None:
    """The point of the demo pack: a judge moves a slider, the plan re-solves."""
    from supplyguard.demo.scenarios import PRELOADED, to_request
    from supplyguard.optimizer.model import solve
    from supplyguard.optimizer.types import Requirement
    from supplyguard.pipeline import load

    context = load()
    rows = context.requirements[
        (context.requirements["plant_id"] == "plant-nigeria")
        & (context.requirements["week"] <= 2)
    ]
    requirements = [
        Requirement(row.material_id, row.plant_id, int(row.week), float(row.required_qty))
        for row in rows.itertuples()
    ]

    request = to_request(PRELOADED["price_only"], requirements)
    baseline = solve(request, context.offers, context.risk)
    assert baseline.status == "optimal"

    # The same demand with risk priced back in, as the slider would send it.
    risk_averse = solve(
        to_request(PRELOADED["baseline"], requirements), context.offers, context.risk
    )
    assert risk_averse.status == "optimal"
    assert risk_averse.high_risk_share <= baseline.high_risk_share
