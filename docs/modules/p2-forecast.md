# P2 — demand forecast and cold start

**What it does.** Forecasts 13 weeks of demand per style, and produces a forecast
for styles that have no history at all.

**Where it lives.** `apps/p2/backend/trendwear/forecast/` — `model.py` (the
LightGBM forecaster), `coldstart.py` (the analogue method).

**Why it matters.** Everything downstream is a function of this number: safety
stock, the production plan, the fabric buy, the reconciliation gap, the
financials. A forecast that is quietly wrong makes every other screen quietly
wrong.

## Measured results

Trained on 2,031 style-weeks to **2023-08-21**, tested on 371 style-weeks from
**2023-08-28**. Chronological, never random. Scored on **real styles only**.

| Method | WAPE | Reading |
|---|---|---|
| **LightGBM** (chosen) | **0.340** | |
| Moving average (4 weeks) | 0.363 | A planner's spreadsheet |
| Seasonal naive (52 weeks) | 0.445 | The standard published baseline |

Also: MAPE 0.560, bias **+2.6%**, MAE 475 units.

**The honest reading.** 24% better than seasonal naive and 6% better than a
moving average. The moving-average margin is the one to quote, because that is
what the forecast is actually replacing. WAPE 0.34 on weekly style-level apparel
demand is a reasonable number — style-level demand is genuinely noisy — but it is
not a triumph, and the bias being near zero matters more for planning than the
absolute error.

## What the model learned

| Feature | Importance |
|---|---|
| `rolling_std_4` | 0.102 |
| `lag_4` | 0.102 |
| `rolling_4` | 0.092 |
| `lag_2` | 0.092 |
| `price_vs_competitor` | 0.090 |
| `price` | 0.089 |
| `lag_1` | 0.089 |
| `discount_pct` | 0.088 |
| `rolling_13` | 0.086 |
| `week_of_year` | 0.065 |

Worth pointing at in the interview: **four of the top ten are price and promotion
variables**. That is the argument for a gradient-boosted model over ARIMA, which
could not have used any of them.

`rolling_std_4` at the top says recent volatility predicts demand level — a style
that has been erratic keeps being erratic. That is a real signal, not an artefact.

## Three decisions

**1. Chronological split.** Train on the past, test on the future. On a
time-series problem a random split is not a mistake, it is a leak.

**2. Lags only, never same-week values.** Every feature is available at the
moment the forecast is made. `lag_1` is last week; there is no feature that peeks.

**3. One global model, not 60.** Styles share seasonality and price response, and
60 separate models would each have 34 training rows. The style enters as features
(category, price band), not as a separate model.

## Cold start: the styles with no history

Half the styles in an apparel range are new every season, so a forecaster that
needs history is a forecaster that cannot plan a season.

**Method.** Find the nearest analogue among styles that do have history —
matching on category, price band and launch timing — and scale its curve to the
new style's expected volume.

**Backtest.** Hold out a real style *entirely* (`P0002`, "Meadow Shirt") and
forecast its 13 weeks from nothing.

| Method | WAPE | Bias |
|---|---|---|
| **Nearest analogue** (chosen) | **0.378** | +0.3% |
| Category average | 0.417 | −1.0% |

A real improvement, and worth saying out loud that it is **one held-out style** —
13 observations. We report it as directional evidence that the method works, not
as a precise accuracy figure. Doing this properly means holding out each of the 20
real styles in turn, which is the first thing we would add.

**Chronos, and why not.** A time-series foundation model is the interesting
alternative here, and the metrics file records plainly that it is not installed on
the build machine. We chose a method that runs offline inside a 2 MB container
over one that would have needed a download during a demo.

## Interfaces

- Consumes: `demand`, `styles` from the ETL layer.
- Produces: `forecast` with `style_id`, `week`, `forecast_units`; and
  `metrics["forecast"]`, `metrics["forecast_importance"]`, `metrics["cold_start"]`.
- The model is fitted by `scripts/build_demo_pack.py` and saved to
  `models/p2/demand.joblib`. The API loads it; it never trains.

## What we would do differently

- **Quantile forecasts** rather than a point forecast, so safety stock uses the
  model's own uncertainty instead of historical sigma
  ([p2-inventory.md](p2-inventory.md) makes the same point from the other side).
- Leave-one-style-out cold-start evaluation across all 20 real styles.
- Weight training rows by `observations`, which the ETL already carries.
- Reconcile the forecast hierarchically (style, category, total) so the aggregate
  a planner sees is consistent with the lines beneath it.
