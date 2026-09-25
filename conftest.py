"""Test configuration shared by every suite.

The raw datasets are 212 MB and gitignored, so a fresh clone — including a CI
runner — has the code but not the data. Tests that read those files skip with a
clear reason instead of failing, and everything else still runs.

Run ``python scripts/fetch_data.py`` to make the skipped tests execute.
"""

from __future__ import annotations

import pytest

from scripts.fetch_data import missing_files

_MISSING = missing_files()

DATA_SKIP_REASON = (
    "raw datasets are not present ("
    + ", ".join(_MISSING[:3])
    + (", ..." if len(_MISSING) > 3 else "")
    + "). Run: python scripts/fetch_data.py"
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_data: needs the raw datasets in data/raw (see scripts/fetch_data.py)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip data-backed tests when the datasets are absent.

    Every test under an application's ``tests/`` directory reads real data, so
    they are marked automatically rather than one decorator at a time.
    """
    if not _MISSING:
        return

    skip = pytest.mark.skip(reason=DATA_SKIP_REASON)
    for item in items:
        path = str(item.path)
        if "apps" in path or item.get_closest_marker("requires_data"):
            item.add_marker(skip)
