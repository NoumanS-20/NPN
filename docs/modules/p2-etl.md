# P2 — ETL and the style master

**What it does.** Turns a public retail dataset into a weekly demand history for
60 styles across 5 stores, and builds the style, plant, fabric, BOM and lane
masters the rest of the application plans against.

**Where it lives.** `apps/p2/backend/trendwear/etl/` — `retail.py` (the real
dataset), `synthesize.py` (everything the dataset does not contain).

**Why it matters.** Every number in TrendWear rests on this layer, and the layer
rests on a synthetic dataset. Saying that clearly, in the code and on the screen,
is the difference between a prototype and a misleading claim.

## The dataset, described accurately

Kaggle's *Retail Store Inventory Forecasting* dataset: two years of store-level
demand across 5 stores, **itself synthetic**. It is labelled
`public-synthetic` on every row and on every screen that shows it.

We chose it over the alternatives because it has the four fields the use case
needs together — units, price, discount and a competitor price — and because the
team decided (recorded in the design document) to keep a Kaggle dataset rather
than invent the demand history from nothing. A synthetic public dataset we can
point at beats a private one we made up.

## The discovery that reshaped this module

The data looked daily. It is not: a style-store pair has **122 to 176
observations over 730 days**, not 730. Treating the gaps as zero-demand days
would have halved every average and made the seasonality wrong.

So the module aggregates to a **weekly rate** — units per observed day, scaled to
seven — and keeps an `observations` count on every row. Downstream, a week with
two observations is not treated as equal in weight to a week with seven. This is
the single most important line in the ETL and it exists because we plotted the
raw counts before trusting them.

Result: **106 usable weeks** for 20 real styles.

## What we generated, and why

The dataset has demand and price. A sales-and-operations plan needs rather more.

| Generated | Count | Method |
|---|---|---|
| Styles | 40, on top of the 20 real | Sampled from the real styles' category, price and launch-timing distributions; `origin = generated` on every row |
| Plants and weekly capacity | 3 | Capacity set so peak utilisation binds — a capacity constraint that never binds teaches nobody anything |
| Fabrics, MOQ, lead time, price | 6 | Apparel-typical values: 5-week lead time, MOQ in the low thousands of metres |
| Bill of materials | one row per style | Metres per unit by category |
| DC-to-store lanes | 5 | Lead time and cost per unit by distance band |
| The merchandising plan | one row per style-week | The forecast times a per-style ambition factor, drawn once per style so a buyer's optimism is consistent across a season rather than random week to week. Averages **+16.1%** |

The full method for each is in [../assumptions.md](../assumptions.md). Two things
to note about how this was done:

**Ambition is drawn once per style, not per week.** A buyer who is 20% optimistic
about a jacket is optimistic about it all season. Drawing per week would have
produced noise that cancels out in aggregate — and the reconciliation gap would
have vanished, which is the one thing the use case is about.

**Capacity is calibrated to bind.** The plants can make 652k units against a
merchandising plan of 696k. That is a deliberate choice of scale: a demo where
supply comfortably exceeds ambition has nothing to reconcile.

## Interfaces

Produces, as typed dataframes:

| Table | Key columns |
|---|---|
| `styles` | `style_id`, `name`, `category`, `price`, `cost`, `launch_week`, `origin` |
| `demand` | `style_id`, `store_id`, `week`, `units`, `price`, `discount_pct`, `observations` |
| `plants`, `capacity` | `plant_id`, `week`, `units_capacity` |
| `fabrics`, `bom` | `fabric_id`, `moq_metres`, `lead_time_weeks`; `style_id`, `metres_per_unit` |
| `lanes` | `dc_id`, `store_id`, `lead_time_weeks`, `cost_per_unit` |

Nothing downstream of this module opens a file or knows where the data came from,
which is what makes the engine reusable —
[../reusability.md](../reusability.md) §1.

## What we would do differently

- Weight the forecast's training rows by `observations`; today the count is carried
  and used for filtering but not as a sample weight.
- A formal schema at the boundary (pandera) rather than runtime column checks.
- Source a real apparel sell-through dataset. The synthetic one has no usable
  price response, which is what forced the assumed elasticity in
  [p2-markdown.md](p2-markdown.md).
