"""Download the source datasets into ``data/raw``.

Raw data is gitignored because it is 212 MB. This script rebuilds it from Kaggle
on a fresh clone, so the repository stays small and the data stays reproducible.

Authentication: a Kaggle account token at ``~/.kaggle/access_token`` (newer
``KGAT_`` format) or the classic ``~/.kaggle/kaggle.json``.

    python scripts/fetch_data.py            # download anything missing
    python scripts/fetch_data.py --check    # report what is missing, download nothing
    python scripts/fetch_data.py --force    # re-download everything
    python scripts/fetch_data.py --list     # print the dataset register
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Dataset:
    """One source dataset, with everything the team needs to cite it."""

    slug: str
    dest: str
    files: tuple[str, ...]
    app: str
    tier: str           # "real" | "public-synthetic"
    licence: str
    purpose: str
    kind: str = "dataset"
    only_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def dest_path(self) -> Path:
        return ROOT / self.dest


DATASETS: list[Dataset] = [
    Dataset(
        slug="divyeshardeshana/supply-chain-shipment-pricing-data",
        dest="data/raw/scms",
        files=("SCMS_Delivery_History_Dataset.csv",),
        app="pr1",
        tier="real",
        licence="unknown on Kaggle; originally published by USAID",
        purpose=(
            "Primary PR1 dataset. 10,324 real purchase orders, 73 vendors across 88 "
            "manufacturing sites, promised versus actual delivery dates, prices, freight and weight."
        ),
    ),
    Dataset(
        slug="shahriarkabir/procurement-kpi-analysis-dataset",
        dest="data/raw/procurement",
        files=("procurement_kpi.csv",),
        app="pr1",
        tier="real",
        licence="CC0-1.0",
        purpose="Disruption labels: cancelled and partially delivered orders, defective units.",
    ),
    Dataset(
        slug="shfarshid/supplier-stability-dataset-for-procurement",
        dest="data/raw/procurement",
        files=("supplier_order_lines.csv",),
        app="pr1",
        tier="public-synthetic",
        licence="CC BY 4.0",
        purpose="Quality labels: material-discrepancy events, supplier fault, rework cost.",
    ),
    Dataset(
        slug="harshsingh2209/supply-chain-analysis",
        dest="data/raw/procurement",
        files=("supply_chain_data.csv",),
        app="pr1",
        tier="public-synthetic",
        licence="CC0-1.0",
        purpose="Lead times, defect rates and manufacturing costs used to sanity-check ranges.",
    ),
    Dataset(
        slug="mustafakeser4/sap-dataset-bigquery-dataset",
        dest="data/raw/sap",
        files=("lfa1.csv", "ekko.csv", "ekpo.csv", "eket.csv", "ekbe.csv", "mara.csv"),
        only_files=("lfa1.csv", "ekko.csv", "ekpo.csv", "eket.csv", "ekbe.csv", "mara.csv"),
        app="pr1",
        tier="public-synthetic",
        licence="MIT",
        purpose=(
            "Google Cloud's public SAP demonstration data (cloud-training-demos."
            "SAP_REPLICATED_DATA). Genuine SAP table structures, simulated contents. Used for the "
            "2,590-vendor catalogue and to show ERP-shaped ingestion. Never quoted as real behaviour."
        ),
    ),
    Dataset(
        slug="anirudhchauhan/retail-store-inventory-forecasting-dataset",
        dest="data/raw/retail",
        files=("retail_store_inventory.csv",),
        app="p2",
        tier="public-synthetic",
        licence="CC0-1.0",
        purpose=(
            "Primary P2 dataset. 73,100 daily rows across 5 stores and 20 products; we use the "
            "14,626 Clothing rows for demand, price, discount and inventory."
        ),
    ),
]


def expected_files() -> list[Path]:
    return [d.dest_path / name for d in DATASETS for name in d.files]


def missing_files() -> list[str]:
    return [str(p.relative_to(ROOT)) for p in expected_files() if not p.exists()]


def _kaggle(args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "kaggle", *args], check=True)


def fetch(dataset: Dataset, force: bool = False) -> bool:
    """Download one dataset. Returns True if anything was downloaded."""
    dataset.dest_path.mkdir(parents=True, exist_ok=True)
    present = all((dataset.dest_path / name).exists() for name in dataset.files)
    if present and not force:
        print(f"  present   {dataset.slug}")
        return False

    print(f"  fetching  {dataset.slug}")
    if dataset.only_files:
        for name in dataset.only_files:
            _kaggle(["datasets", "download", "-d", dataset.slug, "-f", name,
                     "-p", str(dataset.dest_path), "-q", "--force"])
    else:
        _kaggle(["datasets", "download", "-d", dataset.slug,
                 "-p", str(dataset.dest_path), "--unzip", "-q", "--force"])
    return True


def fetch_all(force: bool = False) -> None:
    print(f"Fetching {len(DATASETS)} datasets into data/raw")
    for dataset in DATASETS:
        fetch(dataset, force=force)
    remaining = missing_files()
    if remaining:
        print("\nStill missing (check the Kaggle file names):")
        for name in remaining:
            print(f"  - {name}")
        raise SystemExit(1)
    print("\nAll datasets present.")


def print_register() -> None:
    for d in DATASETS:
        print(f"{d.app.upper():4} {d.tier:18} {d.slug}")
        print(f"     -> {d.dest}  ({', '.join(d.files)})")
        print(f"     licence: {d.licence}")
        print(f"     {d.purpose}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report missing files, download nothing")
    parser.add_argument("--force", action="store_true", help="re-download everything")
    parser.add_argument("--list", action="store_true", help="print the dataset register")
    args = parser.parse_args(argv)

    if args.list:
        print_register()
        return 0

    if args.check:
        missing = missing_files()
        if missing:
            print("Missing:")
            for name in missing:
                print(f"  - {name}")
            return 1
        print(f"All {len(expected_files())} expected files are present.")
        return 0

    fetch_all(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
