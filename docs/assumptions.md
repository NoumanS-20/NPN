# Assumptions register

Every field that is **derived or generated** rather than read from a source file, with the exact rule used.
Each is visible in the applications: generated rows are labelled, and derived fields say where they came from.

The mentor's written ruling of 25 September 2026 permits Kaggle data mixed with generated data. Our own rule
on top of that: **reported accuracy figures are computed on real records only**, so generated data can make a
problem larger but never make a score look better.

## PR1 — SupplyGuard

### Derived from real trading history

| Field | Rule | Why it is needed |
|---|---|---|
| `supplier_id` | Slug of vendor + manufacturing site | A buyer sources from a site, not a company. Performance belongs to the factory |
| `on_time_rate` | 1 − (late orders ÷ orders), per supplier | The use case requires delivery performance in sourcing decisions |
| `avg_lead_days`, `p75_lead_days` | Median and 75th percentile of promised lead time, with a three-level fallback: supplier's own record (3+ observations, 79 suppliers) → product-group median (138) → global median (0). `lead_days_source` records which | Only 38% of orders carry a PO date. Product groups differ materially: ARV ~130 days, HRDT 92, MRDT 63 |
| `capacity_per_week` (supplier level) | 95th percentile of the supplier's weekly volume × 1.5 | Not recorded anywhere; a required constraint |
| `offers.capacity_per_week` (supplier **and material**) | Everything that supplier shipped of that material ÷ weeks in the record × 2.0 — a sustainable rate, not a peak week | What the optimiser actually uses. Peak-week measures gave 60–2,285× the weekly requirement, so no constraint ever bound |
| `moq` | 10th percentile of order quantities for that supplier and material, capped at 20% of weekly capacity | Not recorded; a required constraint. The cap stops a minimum order making a supplier unusable |
| `offers.unit_price` | Median unit price that supplier charged for that material; for qualified suppliers, the material's median shifted by that supplier's own price position, ±8% | Price per supplier-material is what the objective minimises |
| `contract_min_share` | ¼ of their historical share of the product group, capped at 20% | Contract commitments are a required input and no contracts exist in the data |
| `contract_max_share` | 2× their historical share, floor 5%, ceiling 60%, ±5% jitter | The 60% ceiling means no contract can mandate single sourcing |
| `plants` | The eight highest-volume delivery locations | The use case asks for demand by SKU and plant |
| `material_requirements` | Historical consumption per material and plant, rolled forward with a seasonal index | PR1 does not forecast — that is P2's job. This is a deterministic roll-up |
| `approved_supplier_list` | Suppliers with traded history for that material, plus qualified generated suppliers | An approved supplier list is a required input |

### Generated suppliers (~303 of 520)

Distributed across product groups in proportion to the real population, so competition grows where it already
exists. For each statistic we **resample real values and jitter them** rather than fitting a distribution:

| Field | Rule |
|---|---|
| `on_time_rate` | Resampled from real suppliers in the same group, ±3% noise, clipped to [0, 1] |
| `avg_lead_days` | Resampled, ±15% noise, clipped to 7–400 days |
| `avg_unit_price` | Resampled, ±20% noise |
| `historical_volume` | Resampled, ±30% noise |
| `name`, `country` | Generated name; country drawn from those the group really serves |

**Why resampling and not a fitted curve.** The real on-time rate is extremely skewed — a median of 100% with
a thin tail of poor performers. A fitted beta distribution reproduced either the mean or the spread but never
both; one version silently shifted the mean from 0.97 to 0.82 and made every generated supplier look worse
than reality. Resampling preserves the shape by construction and takes one sentence to explain.

Generation is seeded (`SEED = 42` in `supplyguard/config.py`), so every demo run produces the same suppliers.

## P2 — TrendWear Planner

| Field | Rule |
|---|---|
| Styles beyond the real 20 | Resampled from the real styles' seasonality, elasticity and volume, on a six-week launch calendar across three seasons |
| `plant_capacity` | Derived from observed peak weekly sales across the network |
| `fabric_bom` | Metres of fabric per unit, per style category, from a fixed table |
| Fabric MOQ and lead time | Minimum order quantities per fabric, 4–6 week lead times, as the use case states |
| `dc_store_lanes` | One distribution centre per region; transit days and cost per unit scaled by distance band |
| `merchandising_plan` | The statistical forecast shifted by a per-style commercial ambition factor and the season's sales target |
| `safety_stock` | z × σ(forecast error) × √(lead time), service level 95% by default |

## What we do not assume

- We do not give suppliers without trading history a performance score. Their columns stay empty and
  `has_history` is false, so the optimiser and the risk model treat them as unknown rather than average.
- We do not fill missing dates with defaults. `Date Not Captured` and `Pre-PO Process` become missing values.
- We do not infer a freight cost where the file only holds a reference to another document.
