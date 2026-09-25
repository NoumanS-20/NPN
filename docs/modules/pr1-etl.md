# PR1 — data loading (ETL)

**What it does.** Turns three raw files into the two tables the rest of SupplyGuard uses: a purchase-order
history with delivery outcomes, and a supplier catalogue.

**Where it lives.** `apps/pr1/backend/supplyguard/etl/` — `scms.py`, `sap.py`, `suppliers.py`.

**How to run it.**

```bash
python scripts/fetch_data.py --check      # confirm the raw files are present
python -m pytest apps/pr1/tests           # 34 tests covering these loaders
```

## scms.py — the primary dataset

USAID/PEPFAR delivery history: 10,324 purchase orders, 2006–2015, 43 countries. The only tier-1 source
behind our reported risk metrics.

| Measured | Value |
|---|---|
| Supplier entities (vendor × manufacturing site) | 217 |
| Vendors / manufacturing sites | 73 / 88 |
| Late deliveries | **11.49%** |
| Median promised lead time | 100 days |
| Suppliers competing in the largest product group (ARV) | 141 |

**A supplier is a vendor at a site**, because that is what a buyer allocates to. The same vendor shipping
from two factories has two lead times and two delivery records.

**Two traps in this file, both handled deliberately:**

1. **Placeholder dates.** `PO Sent to Vendor Date` contains the literal strings `Date Not Captured` and
   `Pre-PO Process`. Parsed naively these become 1970 timestamps and silently poison every lead-time feature.
   They become missing values instead.
2. **Freight cost is only 60% numeric.** The rest is three different things: `Freight Included in Commodity
   Cost` (the freight really was paid, inside the item price), `See DN-93 (ID#:1281)` (a cross-reference to
   another document), and `Invoiced Separately`. An early version stripped non-digits, which turned that
   cross-reference into a **$931,281 freight charge on 2,445 rows** and would have corrupted every cost
   comparison the optimiser makes. Freight is now parsed strictly and carries two flags: `freight_known`
   (60% of rows) and `freight_bundled` (14%). A regression test fails if reference text ever becomes money
   again.

## sap.py — ERP-shaped ingestion

Google Cloud's public `cloud-training-demos.SAP_REPLICATED_DATA`. **Genuine SAP table structures, simulated
contents** — labelled `public-synthetic` everywhere and excluded from reported accuracy.

Joining `EKET` (the delivery date the vendor committed to) with the earliest goods receipt in `EKBE`
(`vgabe = "1"`) and the vendor on `EKKO` gives **171,380 promised-versus-actual lines, 45.4% late**.

Two judgement calls:
- **Seven headers have no vendor.** All are document type `UB`, stock transport orders that move goods
  between a company's own plants. They are internal transfers, not supplier deliveries, so they are excluded.
- **Five of the 2,590 vendors have no name.** They keep their place in the catalogue with a visible
  placeholder rather than being quietly dropped.

The honest limit: the master holds 2,590 vendors, but only **25** of them ever transact in this extract.

## suppliers.py — the catalogue

One row per supplier entity: 217 with measured history, ~2,590 from the SAP master, 2,807 in total.

**Suppliers without history are marked unknown, not average.** `has_history` is false, and their performance
columns are empty. Giving an untraded vendor a flattering 95% on-time rate would be the easiest way to make
the demo look good and the interview go badly.

**Lead times use a three-level fallback, and record which level they came from.** Only 38% of orders carry a
PO date, so a lead time can be measured for 155 of 217 suppliers and only 65 have five or more observations.

| Level | Rule | Suppliers |
|---|---|---|
| `supplier` | three or more of their own observations | 79 |
| `group` | their product group's median | 138 |
| `global` | the overall median | 0 |

This matters because the groups genuinely differ — ARV about 130 days, HRDT 92, MRDT 63. One global constant
would have flattened exactly the differences the optimiser is supposed to trade off. After the hierarchy,
lead times range from 7 to 320 days with a standard deviation of 40.

## Likely questions

**Why is a supplier a vendor-site pair and not just a vendor?** Because performance is a property of the
factory, not the corporate entity, and a buyer sources from a specific site.

**Your on-time rates look very high.** They are: the median is 100% and the overall late rate is 11.5%, so
most suppliers are on time most of the time. That imbalance is why the risk models report PR-AUC and recall
rather than accuracy.

**Why keep synthetic SAP data at all?** For the ERP shape. It proves the ingestion is not tied to one tidy
CSV, and it gives the catalogue the scale a real procurement system has. It never contributes a reported
accuracy figure.
