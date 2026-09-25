"""Read ERP-shaped procurement data from SAP tables.

Source: Google Cloud's public ``cloud-training-demos.SAP_REPLICATED_DATA``. The
table structures are genuine SAP; the contents are simulated. Everything loaded
here is labelled ``public-synthetic`` and is excluded from the accuracy figures
we report, exactly as ``docs/data-sources.md`` states.

Why keep it at all: it is the same shape a real customer's ERP extract would be,
so it demonstrates that our ingestion is not tied to one tidy CSV. The tables and
the fields that matter:

* ``LFA1`` — vendor master. ``lifnr`` vendor number, ``name1`` name, ``land1``
  country, ``ort01`` city.
* ``EKKO`` — purchase-order header. ``ebeln`` order, ``lifnr`` vendor,
  ``bedat`` order date.
* ``EKPO`` — order item. ``ebelp`` item, ``matnr`` material, ``werks`` plant,
  ``menge`` quantity, ``netpr`` net price.
* ``EKET`` — schedule line. ``eindt`` is the delivery date the vendor committed to.
* ``EKBE`` — order history. ``vgabe == "1"`` marks a goods receipt and ``budat``
  is when it was actually posted.

Joining EKET's promised date to EKBE's earliest goods receipt gives a real
promised-versus-actual comparison across 158,942 lines.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_GOODS_RECEIPT = "1"


def _read(sap_dir: Path, table: str, columns: list[str]) -> pd.DataFrame:
    path = sap_dir / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run: python scripts/fetch_data.py")
    return pd.read_csv(path, low_memory=False, usecols=columns)


def load_vendor_master(sap_dir: Path) -> pd.DataFrame:
    """One row per vendor from LFA1 — the wider supplier catalogue."""
    raw = _read(sap_dir, "lfa1", ["lifnr", "name1", "land1", "ort01", "ktokk"])

    df = pd.DataFrame({
        "supplier_id": "sap-" + raw["lifnr"].astype(str).str.strip().str.lstrip("0"),
        "name": raw["name1"].astype("string").str.strip(),
        "country": raw["land1"].astype("string").str.strip(),
        "city": raw["ort01"].astype("string").str.strip(),
        "account_group": raw["ktokk"].astype("string").str.strip(),
    })

    # LFA1 holds 3,035 rows for 2,590 vendors (repeated addresses), and five of
    # those vendors carry no name. We keep every vendor rather than silently
    # losing five, and give the unnamed ones a visible placeholder.
    blank = df["name"].isna() | (df["name"].str.len() == 0)
    df.loc[blank, "name"] = "Vendor " + df.loc[blank, "supplier_id"].str.removeprefix("sap-")
    df = df.drop_duplicates(subset="supplier_id", keep="first")
    df["origin"] = "public-synthetic"
    df["source"] = "sap"
    return df.sort_values("supplier_id", kind="mergesort").reset_index(drop=True)


def load_po_outcomes(sap_dir: Path) -> pd.DataFrame:
    """Promised versus actual delivery, one row per purchase-order schedule line."""
    headers = _read(sap_dir, "ekko", ["ebeln", "lifnr", "bedat", "bsart"])
    # Seven headers carry no vendor; all are document type UB, stock transport
    # orders that move goods between a company's own plants. They are internal
    # transfers, not supplier deliveries, so they do not belong in supplier risk.
    headers = headers[headers["lifnr"].notna()].drop(columns="bsart")
    schedule = _read(sap_dir, "eket", ["ebeln", "ebelp", "eindt", "menge", "wemng"])
    history = _read(sap_dir, "ekbe", ["ebeln", "ebelp", "vgabe", "budat", "menge"])

    receipts = history[history["vgabe"].astype(str).str.strip() == _GOODS_RECEIPT]
    first_receipt = (
        receipts.groupby(["ebeln", "ebelp"], as_index=False)["budat"].min()
        .rename(columns={"budat": "received_date"})
    )

    merged = schedule.merge(first_receipt, on=["ebeln", "ebelp"], how="inner")
    # Inner join on the header: a schedule line whose purchase order is not in
    # EKKO has no vendor, and a delivery outcome with no supplier teaches the
    # risk model nothing.
    merged = merged.merge(headers, on="ebeln", how="inner")

    df = pd.DataFrame({
        "po_id": merged["ebeln"].astype(str) + "-" + merged["ebelp"].astype(str),
        "supplier_id": "sap-" + merged["lifnr"].astype(str).str.strip().str.lstrip("0"),
        "promised_date": pd.to_datetime(merged["eindt"], errors="coerce"),
        "received_date": pd.to_datetime(merged["received_date"], errors="coerce"),
        "order_date": pd.to_datetime(merged["bedat"], errors="coerce"),
        "qty": pd.to_numeric(merged["menge"], errors="coerce").fillna(0.0),
        "received_qty": pd.to_numeric(merged["wemng"], errors="coerce").fillna(0.0),
    })

    df = df[df["promised_date"].notna() & df["received_date"].notna()].copy()
    df["late_days"] = (df["received_date"] - df["promised_date"]).dt.days
    df["is_late"] = (df["late_days"] > 0).astype(int)
    df["promised_lead_days"] = (df["promised_date"] - df["order_date"]).dt.days
    df["origin"] = "public-synthetic"
    df["source"] = "sap"

    return df.sort_values(["promised_date", "po_id"], kind="mergesort").reset_index(drop=True)


def summarise(vendors: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, float | int]:
    return {
        "vendors": int(vendors["supplier_id"].nunique()),
        "countries": int(vendors["country"].nunique()),
        "schedule_lines": int(len(outcomes)),
        "vendors_with_history": int(outcomes["supplier_id"].nunique()),
        "late_rate": round(float(outcomes["is_late"].mean()), 4),
        "median_late_days_when_late": float(
            outcomes.loc[outcomes["is_late"] == 1, "late_days"].median()
        ),
    }
