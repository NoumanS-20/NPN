"""The data fetch script is how a fresh clone rebuilds data/raw.

Raw data is gitignored, so these tests guard the contract that every dataset we
depend on is declared, reachable and documented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fetch_data import DATASETS, expected_files, missing_files

ROOT = Path(__file__).resolve().parents[1]


def test_datasets_are_declared() -> None:
    assert DATASETS, "no datasets declared"


def test_every_dataset_lands_under_data_raw() -> None:
    for d in DATASETS:
        assert d.dest.startswith("data/raw/"), f"{d.slug} writes outside data/raw: {d.dest}"
        assert d.kind in {"dataset", "competition", "file"}


def test_every_dataset_declares_its_licence_and_purpose() -> None:
    for d in DATASETS:
        assert d.licence, f"{d.slug} has no licence recorded"
        assert d.purpose, f"{d.slug} has no purpose recorded"
        assert d.app in {"pr1", "p2"}, f"{d.slug} is not assigned to an application"


def test_expected_files_are_listed_for_each_dataset() -> None:
    for d in DATASETS:
        assert d.files, f"{d.slug} lists no files, so nothing can be verified"


@pytest.mark.requires_data
def test_the_current_checkout_has_every_expected_file() -> None:
    """Fails loudly if a dataset is deleted from a checkout that should have them.

    Skipped where the data was never fetched — a fresh clone or a CI runner
    without Kaggle credentials — because that is a missing download, not a bug.
    """
    assert missing_files() == [], f"missing data files: {missing_files()}"


def test_expected_files_resolve_to_real_paths() -> None:
    for path in expected_files():
        assert str(path).startswith(str(ROOT)), f"{path} escapes the repository"
