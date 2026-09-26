# Alternatives considered

"Alternatives considered" is on the judging list, so this is written as a record
of real decisions, including the two we got wrong first and changed.

Each entry: what we chose, what we rejected, and why. Where a choice was close,
it says so.

---

## 1. Optimisation: PuLP + CBC

**Chosen.** PuLP with the bundled CBC solver, for both the supplier allocation
MILP (PR1) and the production LP (P2).

| Rejected | Why not |
|---|---|
| **Google OR-Tools** (CP-SAT) | Genuinely better: faster on integer problems and a nicer scheduling API. Rejected because CBC solves our largest instance — eight plants, eight weeks, 376 offers — in about eight seconds, and one plant-week in about 0.3. We do not need the speed, and PuLP's model reads like the algebra we wrote in the design document, which matters when four people have to explain it. If the model grew a changeover-sequencing constraint, we would move. |
| **A greedy heuristic** (sort by risk-adjusted price, fill capacity) | We built it anyway — it is `baselines/cheapest_first`. It is 6.4% cheaper on the invoice and carries 1.3 points more high-risk volume, and it cannot honour "at least two suppliers per material" and a 40% concentration cap at the same time. Keeping it as the baseline is worth more than using it as the answer. |
| **scipy.optimize.linprog** | No integer variables, so no MOQ and no "supplier used" binary. That kills two of the six constraint families. |
| **Gurobi / CPLEX** | Licensed. A hackathon prototype a judge cannot run is not a prototype. |

**Version note.** PuLP 4.0 removed the classic `LpVariable(lowBound=...)` API and
broke the model on install. Pinned to `>=2.9,<3` with the reason in the comment.

---

## 2. Delay prediction: random forest

**Chosen.** Random forest, selected by a measured bake-off, PR-AUC **0.347**
against a best baseline of 0.264 and ROC-AUC 0.825 on 2,581 held-out orders.

| Rejected | Measured result |
|---|---|
| **XGBoost** | PR-AUC 0.334, recall 0.088. Ranked almost as well and caught almost nothing at a usable threshold. |
| **Logistic regression** | PR-AUC 0.287, recall 0.838, precision 0.260. Kept as the interpretable comparison; the panel can see the trade. |
| **A neural network** | 10,324 rows and 14% positives. An MLP on that is a way to overfit slowly. We did not build it and we would say the same again. |
| **Isotonic calibration on top** | Tried, and it *destroyed* the model: PR-AUC fell 0.345 to 0.231, below baseline. Removed. Cross-validated calibration inside the training period was kept where it helped. |

All three candidates are trained, scored and reported — the Models screen shows
the bake-off, not just the winner. The split is chronological (train to Dec 2013,
test 2014–2015); a random split on time-series data would have inflated every
number here.

**The two we refused to ship.** Quality (PR-AUC 0.164 against a 0.256 baseline)
and disruption (ROC-AUC 0.482, barely better than chance) both failed the
sufficiency gate, so they fall back to the supplier's observed rate and say so on
screen. 71 and 136 positive labels are not enough to learn from, and pretending
otherwise would have been the single worst thing in this project.

---

## 3. Demand forecast: LightGBM

**Chosen.** LightGBM on lag and rolling features, WAPE **0.337** against 0.445
for seasonal naive and 0.3625 for a moving average.

| Rejected | Why not |
|---|---|
| **ARIMA / SARIMA per style** | 60 styles means 60 models to fit, tune and explain, and it cannot use price, discount or competitor price — which are four of the top ten features by importance. |
| **Prophet** | Built for daily series with holidays. Ours is weekly, 106 weeks, sparse. It would have been a heavier dependency for a worse number. |
| **Chronos / a time-series foundation model** | Genuinely interesting for the cold-start case, and the metrics file records that it is not installed on the build machine. We used a nearest-analogue method instead: WAPE 0.378 against 0.417 for the category average. A pretrained model we could not run offline in a Space was not worth the risk. |
| **A single global neural forecaster** | Same objection as above, plus 2,031 training rows. |

---

## 4. Markdown elasticity: a published figure, not our fit

**Chosen.** A published apparel price elasticity of **-1.8**, labelled "assumed"
in the API, in the metrics file, and on the screen.

**Rejected:** our own log-log fit on the data. We built it. It explains **0.0%**
of the variation (slope 0.04), which means the dataset contains no usable price
response. Shipping that curve would have produced confident recommendations
resting on noise.

This is the decision we are most likely to be challenged on and the one we are
most comfortable defending: the recommendation engine still works, the timing
logic is driven by measured sell-through, and the one number we could not measure
is named as an assumption everywhere it appears.

---

## 5. Front end: plain HTML, CSS and ES modules

**Chosen.** No framework, no build step, no bundler. Chart.js from a local
pinned copy. 32 tests under `node --test` with jsdom.

| Rejected | Why not |
|---|---|
| **React / Vite** | A build step between our code and the page a judge sees, `node_modules`, and a second toolchain for a four-person team with one week. Thirteen screens of tables and charts do not need a virtual DOM. |
| **Streamlit** | Fastest to a screen, and the wrong answer here. Judging includes UI, UX and visual appeal, and Streamlit apps look like Streamlit apps. It also owns the request cycle, which makes "click a scenario, watch the solve time" awkward. |
| **Plotly Dash** | Same objection, heavier. |
| **A CDN for Chart.js** | Rejected after deciding the demo must work offline. The vendored copy is pinned and 200 KB. |

The cost of this choice is real: we wrote our own sortable table (~150 lines) and
our own chart helpers. The benefit is that the app has no build, starts in
seconds, and a stale-module bug during development was fixed with two lines of
cache headers rather than a bundler config.

---

## 6. Storage: parquet files, with SQLite for a cache

**Chosen.** Processed tables as parquet, models as joblib, SQLite where a
database is genuinely convenient.

| Rejected | Why not |
|---|---|
| **PostgreSQL** | Right for production, wrong for a demo that must start offline on a laptop and inside a 31 MB container. It would add a service to start, a schema to migrate and a failure mode on the day. |
| **A data warehouse** (BigQuery, Snowflake) | Same, plus a network dependency and a bill. |
| **CSV** | 892 KB of parquet against several MB of CSV, no dtypes, and slower loads. Parquet also preserves the origin flags as categories. |

[architecture.md](architecture.md) §5 is explicit that a real deployment replaces
this layer, and [estimate-and-roadmap.md](estimate-and-roadmap.md) costs it.

---

## 7. One repository with two applications

**Chosen.** One repository, `apps/pr1` and `apps/p2`, with the separation
enforced by a test.

**Rejected:** two repositories. The mentor's ruling was two separate
non-overlapping *solutions*, not two separate repositories — and two repositories
for a four-person team would have meant two CI pipelines, two review queues and
duplicated front-end components, in exchange for a separation we can prove with
eleven lines of test.

**Rejected:** one application with a mode switch. This is what the ruling
forbids, and it would also have been worse: the two use cases share no entities.

---

## 8. Hosted inference rather than a local LLM

**Chosen.** For the narrative explanations, deterministic template generation
from the solved plan — no model call at all in the shipped path — with Hugging
Face hosted inference available behind a key for the free-text summaries.

| Rejected | Why not |
|---|---|
| **A local LLM** (Llama, Mistral via llama.cpp) | The build machine has 8 GB of RAM and an RTX 3050. A 7B model would make the demo slow and the container enormous. |
| **An LLM in the decision path** | Rejected on principle. A number a judge sees must come from the optimiser or the model, not from a language model's paraphrase of one. The narrative explains the plan; it never produces it. |
| **Commercial hosted LLM APIs** | A key we would have to fund and rotate, and a network dependency in a demo we decided must work offline. |

---

## 9. Two we got wrong first, and changed

Recording these because the corrections are the actual engineering.

**Freight parsing.** The SCMS freight column contains values like
`"See DN-93 (ID#:1281)"`. Stripping non-digits turned that into **931,281** — in the source column, which is dollars — on
2,445 rows. Fixed with strict numeric parsing plus explicit `freight_known` and
`freight_bundled` flags, and a named regression test. Every freight figure is now
either a number or absent, never a fabricated one.

**Supplier capacity scale.** Set wrong twice — first from a quarterly total, then
from a weekly p95 — giving coverage ratios of 245x and then 86x, which made the
capacity constraint decorative. Fixed to a sustainable weekly rate per supplier
*and material*, scaled by plant share. This is why the constraint now binds and
the plan is interesting.

Both are in [assumptions.md](assumptions.md), and both have tests that would
catch a regression.
