"""Look inside a parquet file from the terminal.

Parquet is a binary format. Opening one in VS Code shows you nothing useful, so
this prints it as a readable table instead.

    # list every parquet file in the project, with its size and row count
    .venv\\Scripts\\python.exe scripts\\peek.py

    # show the first rows of one file
    .venv\\Scripts\\python.exe scripts\\peek.py offers

    # show more rows, or every column
    .venv\\Scripts\\python.exe scripts\\peek.py offers --rows 20
    .venv\\Scripts\\python.exe scripts\\peek.py suppliers --describe

    # write it out as a spreadsheet you can open in Excel
    .venv\\Scripts\\python.exe scripts\\peek.py offers --csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"


def find(name: str) -> Path | None:
    """Match a file by the shortest thing you can type.

    "offers" finds pr1-v1/offers.parquet. If two apps both have a table with
    that name, the full path decides it.
    """
    matches = [p for p in DATA.rglob("*.parquet") if name in p.stem or name in str(p)]
    if not matches:
        return None
    if len(matches) > 1:
        print(f"'{name}' matches {len(matches)} files - be more specific:")
        for p in matches:
            print(f"   {p.relative_to(DATA).as_posix()}")
        raise SystemExit(1)
    return matches[0]


def catalogue() -> None:
    """Every parquet file, how big it is, and what is in it."""
    files = sorted(DATA.rglob("*.parquet"))
    if not files:
        print("No parquet files yet. Build them: python scripts/build_demo_pack.py")
        return

    print(f"{len(files)} tables in data/processed\n")
    app = None
    for path in files:
        folder = path.parent.name
        if folder != app:
            app = folder
            label = "SupplyGuard (PR1)" if folder.startswith("pr1") else "TrendWear (P2)"
            print(f"  {label}")
        # Reading only the metadata would be faster, but these are all small and
        # the row count is the thing you actually want to see.
        frame = pd.read_parquet(path)
        size = path.stat().st_size / 1024
        print(
            f"     {path.stem:20} {len(frame):>6,} rows  "
            f"{len(frame.columns):>3} cols  {size:>7,.0f} KB"
        )
    print("\n  Show one with:  python scripts/peek.py <name>")


def show(path: Path, rows: int, describe: bool, to_csv: bool) -> None:
    frame = pd.read_parquet(path)

    print(f"\n{path.relative_to(ROOT).as_posix()}")
    print(f"{len(frame):,} rows x {len(frame.columns)} columns\n")

    print("COLUMNS")
    for name, dtype in frame.dtypes.items():
        missing = frame[name].isna().sum()
        note = f"   ({missing:,} missing)" if missing else ""
        print(f"   {name:28} {str(dtype):12}{note}")

    print(f"\nFIRST {rows} ROWS")
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print(frame.head(rows).to_string())

    if describe:
        print("\nNUMBERS, SUMMARISED")
        with pd.option_context("display.width", 200):
            print(frame.describe().round(3).to_string())

    if to_csv:
        out = ROOT / "build" / f"{path.stem}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out, index=False, encoding="utf-8-sig")  # -sig so Excel reads it
        print(f"\nWritten to {out.relative_to(ROOT).as_posix()} - open it in Excel.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?", help="part of a file name, e.g. offers")
    parser.add_argument("--rows", type=int, default=10)
    parser.add_argument("--describe", action="store_true", help="min/max/mean per column")
    parser.add_argument("--csv", action="store_true", help="also write a CSV for Excel")
    args = parser.parse_args(argv)

    if not args.name:
        catalogue()
        return 0

    path = find(args.name)
    if path is None:
        print(f"Nothing matches '{args.name}'. Run without arguments to list them all.")
        return 1

    show(path, args.rows, args.describe, args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
