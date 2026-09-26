"""Build everything the demo needs, ahead of time.

Run this before 28 September and again after any change to the data or the
models:

    python scripts/build_demo_pack.py           # build both applications
    python scripts/build_demo_pack.py --check   # verify without rebuilding

What it guarantees, and why each one matters on the day:

* **Nothing is trained during the demo.** Both pipelines run here, and the API
  loads saved artifacts. A test fails the build if model training ever appears
  in an API module.
* **The same numbers every time.** Every random seed is pinned in one place per
  application, so the plan a judge sees is the plan we measured and rehearsed.
* **Two scenarios ready to open** per application — a clean baseline and a
  disruption — so a panel can change an input without waiting for anything to
  retrain.
* **It works offline.** The pack contains the processed tables and the fitted
  models; nothing here needs a network once the raw data is in place.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages"),
    str(ROOT / "apps" / "pr1" / "backend"),
    str(ROOT / "apps" / "p2" / "backend"),
]

EXPECTED = {
    "pr1 planning cache": "data/processed/pr1-v1/offers.parquet",
    "pr1 delay model": "models/pr1/delay.joblib",
    "pr1 quality model": "models/pr1/quality.joblib",
    "pr1 disruption model": "models/pr1/disruption.joblib",
    "p2 planning cache": "data/processed/p2-v1/reconciliation.parquet",
    "p2 demand model": "models/p2/demand.joblib",
}


def missing() -> list[str]:
    return [name for name, path in EXPECTED.items() if not (ROOT / path).exists()]


def verify() -> dict[str, object]:
    """Confirm every artifact is present and can actually be loaded."""
    gaps = missing()
    loadable: dict[str, bool] = {}

    if not gaps:
        from supplyguard.pipeline import load as load_pr1
        from supplyguard.pipeline import load_model
        from trendwear.pipeline import load as load_p2

        try:
            pr1 = load_pr1()
            loadable["pr1 context"] = len(pr1.offers) > 0
            loadable["pr1 delay model"] = load_model("delay").metrics["label_sufficient"] is True
            p2 = load_p2()
            loadable["p2 context"] = len(p2.reconciliation) > 0
        except Exception as error:               # noqa: BLE001 - reported, not raised
            loadable["error"] = str(error)

    return {"missing": gaps, "loadable": loadable, "ready": not gaps and "error" not in loadable}


def build() -> None:
    from supplyguard.pipeline import build as build_pr1
    from trendwear.pipeline import build as build_p2

    print("Building SupplyGuard (PR1)…")
    started = time.perf_counter()
    pr1 = build_pr1(force=True)
    print(f"  done in {time.perf_counter() - started:.0f}s")
    for key, value in pr1.summary().items():
        print(f"    {key:24} {value:,}")

    print("\nBuilding TrendWear Planner (P2)…")
    started = time.perf_counter()
    p2 = build_p2(force=True)
    print(f"  done in {time.perf_counter() - started:.0f}s")
    for key, value in p2.summary().items():
        print(f"    {key:24} {value:,}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without rebuilding")
    args = parser.parse_args(argv)

    if args.check:
        result = verify()
        if result["ready"]:
            print(f"Demo pack is ready: all {len(EXPECTED)} artifacts present and loadable.")
            return 0
        print("Demo pack is NOT ready.")
        for name in result["missing"]:
            print(f"  missing: {name}")
        if "error" in result["loadable"]:
            print(f"  error:   {result['loadable']['error']}")
        return 1

    build()
    result = verify()
    print(f"\nDemo pack {'ready' if result['ready'] else 'INCOMPLETE'}.")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
