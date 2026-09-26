# Reusability

What another team can take from this, what they would have to change, and what is
specific to these two use cases. "Reusability" is on the judging list, so this is
written as an honest inventory rather than a sales pitch.

The short version: **the planning engines are reusable, the ETL is not, and the
boundary between them is a typed dataframe.**

---

## 1. The boundary

Every module downstream of `etl/` takes dataframes with named columns and returns
dataframes. Nothing below the ETL layer opens a file, knows a path, or knows that
the data came from Kaggle.

That means adopting either application is a rewrite of one layer:

```
   your SAP extract / warehouse query / CSV drop
                    |
                    v
   etl/  <--- you replace this, and only this
                    |
                    v  a dataframe with the columns below
   features -> models -> optimiser -> scenarios -> API -> screens
        (unchanged)
```

### What SupplyGuard's engine needs from you

| Table | Required columns |
|---|---|
| `suppliers` | `supplier_id`, `name`, `country`, `origin` |
| `offers` | `supplier_id`, `material_id`, `unit_price`, `lead_days`, `capacity_qty`, `moq`, `week` |
| `approvals` | `supplier_id`, `material_id` (the approved supplier list) |
| `requirements` | `material_id`, `plant_id`, `week`, `required_qty` |
| `orders` (history) | `supplier_id`, `material_id`, `order_date`, `promised_date`, `actual_date`, `qty` — only needed to train the risk models |

Give it those five and the optimiser, the risk scoring, the four scenarios, the
three baselines, the narrative and all six screens work unchanged.

### What TrendWear's engine needs from you

| Table | Required columns |
|---|---|
| `styles` | `style_id`, `name`, `category`, `price`, `cost`, `launch_week`, `origin` |
| `demand` (history) | `style_id`, `store_id`, `week`, `units`, `price`, `discount_pct` |
| `capacity` | `plant_id`, `week`, `units_capacity` |
| `bom` | `style_id`, `fabric_id`, `metres_per_unit` |
| `fabrics` | `fabric_id`, `moq_metres`, `lead_time_weeks`, `price_per_metre` |
| `lanes` | `dc_id`, `store_id`, `lead_time_weeks`, `cost_per_unit` |

---

## 2. Reusable as it stands

These need no change at all to be used on a different problem.

| Component | Where | What it is |
|---|---|---|
| **Sufficiency gate** | `risk/base.py` | Train candidates, score against named baselines, and ship the model only if it beats them by a real margin — otherwise fall back to an observed rate and record why. This pattern is the single most portable thing in the repository. |
| **Chronological splitting** | `packages/pyshared/timeutil.py` | `time_split` and `to_week_start`. No random splits on time-series data, ever. |
| **Metrics reporting** | `packages/pyshared/metrics.py` | Classification and regression reports as plain dicts, with baselines beside the result. |
| **Telemetry** | `packages/pyshared/telemetry.py` | Per-endpoint request counts, error rate and p50/p95 latency, plus a response-time header. ~110 lines, no external collector. |
| **Front-end kit** | `packages/web/` | Design tokens with a risk ramp kept separate from the accent colour, a base layout, a sortable table where numeric columns open descending and missing values sort last, chart helpers, and formatters. No framework, no build step. |
| **Safety stock** | `p2/inventory/safety_stock.py` | `z x sigma x sqrt(L)` with a backtest that reports the *achieved* service level, not the planned one. |
| **Wagner-Whitin lot sizing** | `p2/fabric/lotsize.py` | Dynamic lot sizing against MOQ and lead time. Textbook, correct, and independent of apparel. |
| **Demo pack pattern** | `scripts/build_demo_pack.py` | Pre-train everything, pin every seed in one place, and fail the build if training code appears in an API module. Any team doing a live demo of a model should copy this. |

---

## 3. Reusable with a change of parameters

| Component | What you change |
|---|---|
| **The allocation MILP** | The objective terms and which constraint families you switch on. The model is assembled from named constraint builders in `optimizer/model.py`, so dropping "at least two suppliers per material" is deleting one call. |
| **The scenario engine** | Four scenarios, each a function that perturbs the input tables and re-solves. Adding "a port closes" is one function and one registry entry. |
| **The production LP** | Capacity, changeover and horizon are config values. |
| **The S&OP cycle** | Five stages and their labels are a list in `sop/cycle.py`. A different company's cycle is a different list. |
| **Risk pricing** | The shortage penalty and rework cost are config constants, and they are the two numbers that decide how much extra the plan will pay to avoid risk. Anyone adopting this must set them from their own cost of a stockout. |

---

## 4. Specific to these use cases, and not reusable

Said plainly, because claiming otherwise is how a reusability answer falls apart:

- **All six ETL modules.** They parse particular Kaggle files with particular
  quirks — the SCMS freight column, the SAP demo export's layout, the retail
  set's sparse dailies. None of it survives contact with another dataset.
- **The synthetic generators.** `etl/synthesize.py` in both applications invents
  suppliers, offers, capacity, styles and a merchandising plan because the source
  data lacks them. The *method* is reusable as a pattern; the distributions are
  fitted to these datasets and documented in [assumptions.md](assumptions.md).
- **The narrative templates.** They name procurement and apparel concepts.
- **The 16 materials, 8 plants, 60 styles, 6 fabrics.** Fixtures, not features.
- **Every measured number in the documentation.** Ours, on our data.

---

## 5. What an adopter actually does

In order, with our own estimate of effort for someone who knows their data:

1. **Write one ETL module** producing the five (PR1) or six (P2) tables above.
   Two to five days, depending on how clean the source is. This is the whole job.
2. **Set the two risk prices** — cost of a late delivery, cost of a quality
   event — in `config.py`. Half a day, mostly arguing with finance.
3. **Decide which constraints apply.** Concentration caps and contract minimums
   are policy, not code. One day.
4. **Re-run the sufficiency gate.** With more positive labels than our 71 and 136,
   the quality and disruption models may well pass, and nothing else changes: the
   gate decides, and the screens report whatever it decides.
5. **Rebuild the demo pack and run the tests.** An afternoon.

Roughly **one to two weeks** to a working planning engine on a new dataset,
against the eight weeks in [estimate-and-roadmap.md](estimate-and-roadmap.md) for
building it from nothing. That ratio is the case for reuse, and it holds only
because of the boundary in §1.

---

## 6. What we would change to make it more reusable

Not claiming these are done:

- The required columns above are checked at runtime with clear errors, but there
  is no formal schema (pandera or pydantic) an adopter could validate against
  before writing any code.
- Config is Python constants. A YAML profile per deployment would be better.
- The two applications each have their own `pipeline.py` with the same shape.
  A shared pipeline runner would remove about sixty lines of duplication — we left
  it deliberately, because collapsing them would create the coupling the
  separation rule exists to prevent.
