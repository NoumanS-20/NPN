"""The two applications must stay independent.

The mentor ruled on 25 September 2026 that P2 and PR1 are separate use cases and
must have non-overlapping solutions. These tests make that rule enforceable
rather than aspirational: they fail the build if either application reaches into
the other, or if shared code starts holding domain logic.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
SHARED = ROOT / "packages" / "pyshared"


def _python_files(app: str) -> list[Path]:
    return [p for p in (APPS / app).rglob("*.py") if "__pycache__" not in p.parts]


PACKAGES = {"pr1": "supplyguard", "p2": "trendwear"}


def test_both_applications_exist() -> None:
    for app, package in PACKAGES.items():
        assert (APPS / app / "backend" / package).is_dir(), f"apps/{app}/{package} is missing"


def test_apps_never_import_each_other() -> None:
    for app, forbidden in (("pr1", "trendwear"), ("p2", "supplyguard")):
        for path in _python_files(app):
            text = path.read_text(encoding="utf-8")
            assert forbidden not in text, f"{path} imports the other application"


def test_shared_package_holds_no_domain_logic() -> None:
    banned = re.compile(r"\b(supplier|allocation|markdown|forecast|risk_score|style)\b", re.I)
    for path in SHARED.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert not banned.search(line), f"{path} contains domain logic: {line.strip()}"
