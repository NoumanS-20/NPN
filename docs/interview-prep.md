# Interview preparation

For the technical interview on **30 September 2026**. Every number here is
measured and comes from `data/processed/*/metrics.json` or a live API response —
none of it is aspirational.

Read §1 for the numbers you must know cold, §2 module by module, and §3 for the
questions most likely to be asked. §4 is the list of things we will volunteer
before anyone has to ask.

---

## 1. The numbers to know cold

### SupplyGuard (PR1)

| | |
|---|---|
| Purchase-order history | 10,324 real orders (SCMS delivery history) |
| Suppliers | 520 — 217 derived from real vendors, 303 generated |
| Plants / materials | 8 / 16 |
| Requirements planned | 384 lines, 1.80 M units, 8-week horizon |
| Delay model | random forest, **PR-AUC 0.347** vs 0.264 best baseline, ROC-AUC 0.825, precision 0.414, recall 0.375, threshold 0.415, on 2,581 held-out orders |
| Quality model | **not sufficient** (PR-AUC 0.164 vs 0.256 baseline) → supplier observed rate |
| Disruption model | **not sufficient** (ROC-AUC 0.482) → supplier observed rate |
| Plan vs how they actually bought | **−25.0% total cost, −12.4% expected late units** |
| Plan vs cheapest-first | +6.4% invoice, **−1.3 points** high-risk volume |
| Solve time | 0.28–0.41 s one plant / two weeks (median 0.30 over 5 runs); 7.9 s all eight plants |

### TrendWear Planner (P2)

| | |
|---|---|
| Styles | 60 — 20 from the data, 40 generated |
| History | 106 weeks, 5 stores, 3 plants, 6 fabrics |
| Forecast | LightGBM, **WAPE 0.340** vs 0.445 seasonal naive, 0.3625 moving average |
| Cold start | analogue method, **WAPE 0.378** vs 0.417 category average |
| Safety stock | 95% planned, **96.8% achieved** over 2,722 style-weeks |
| Reconciliation | merchandising 696k · forecast 600k · supply 652k · **gap 99,686 units = 5.56 M** · consensus 596,462 |
| Merchandising ambition | **+16.1%** above the statistical forecast |
| Financials | revenue 32.9 M, gross margin 18.0 M (54.6%), inventory 1.26 M, distribution 0.47 M |
| Markdown | 10 styles recommended, 159 k margin recovered, elasticity **−1.8 assumed** |
| Production | peak capacity use 100%, zero shortfall, LP solves in 0.2 s |

### The repository

350 Python tests, 32 JavaScript tests, ruff clean, 13 screens, two containers.

---

## 2. Module by module

Each entry: what it does, why this method, and what we would do differently.

### PR1 — ETL and provenance

**What.** Six Kaggle datasets into typed tables, every row labelled `real`,
`public-synthetic` or `generated`. Metrics are computed on real rows only.

**Why.** Because the first question a competent panel asks is "is this real
data?", and the only defensible answer is one you can point at per row. Only the
SCMS delivery history is genuinely real transaction data; the SAP set is Google
Cloud demo data, not a real SAP export, and we corrected our own documentation
when we realised we had described it wrongly.

**Differently.** A formal schema (pandera) at the boundary rather than runtime
column checks.

### PR1 — Point-in-time features

**What.** Every supplier feature — prior late rate, prior volume, prior average
delay — computed with `shift(1)` and expanding windows, so a row never sees its
own outcome or anything after it.

**Why.** It is the difference between a model and a leak. `supplier_prior_late_rate`
is the top feature at 0.211 importance; computed naively it would have included
the label.

**Differently.** Nothing. This is the part we would defend hardest.

### PR1 — Risk models and the sufficiency gate

**What.** Three targets — delay, quality event, disruption. For each, train
logistic regression, random forest and XGBoost, score all three against a majority
baseline and a prior-rate baseline on a chronological split, and ship a model only
if it beats the best baseline by at least 0.03 PR-AUC with ROC-AUC above 0.58.
Otherwise fall back to the supplier's observed rate and record why.

**Why.** Two of the three failed. Quality has 71 positive labels, disruption 136.
A gate that lets a model through on 71 positives is a gate that ships noise as a
prediction, and the optimiser prices those probabilities in money — so a bad model
would not just be wrong, it would change what we buy.

**Differently.** With real labelled history, all three would likely pass. We would
also add conformal prediction intervals rather than point probabilities.

### PR1 — The allocation MILP

**What.** Minimise material cost + expected shortage cost + expected rework cost,
subject to: demand met in full, approved suppliers only, per-supplier-material-week
capacity, lead time inside the horizon, minimum order quantity, at least two
suppliers per material, no supplier above 40% of a material, and both halves of
each contract band — the ceiling and the **contracted minimum**. PuLP + CBC.

Honouring the floors costs money: on a one-week slice it adds 8.1% to the plan
and pulls in three more suppliers, because a commitment made last year does not
care what this week's cheapest quote is. Where a slice cannot satisfy every
floor at once, the plan is still returned and the message says the minimums were
waived — the same escalation the concentration cap already uses.

**Why.** Risk has to be in the objective in money, or it is a report rather than a
decision. That single choice is why the plan pays 6.4% more on the invoice and
carries 1.3 points less high-risk volume. The constraint families come from the
mentor's written reply.

**Differently.** OR-Tools CP-SAT if we needed changeover sequencing or a network
ten times this size.

### PR1 — Baselines and the comparison

**What.** Three baselines, all solved and reported: cheapest-first, equal split,
and the historical mix (how this organisation actually bought).

**Why.** "Our optimiser saved 25.0%" means nothing without saying against what.
Including the baseline that *beats* us on invoice price is the reason to believe
the rest.

**Differently.** Add a rolling backtest: run the plan weekly over the last year of
history and compare cumulative realised cost, not one slice.

### PR1 — Scenarios

**What.** Four: supplier outage, demand spike, lead-time shock, price shock. Each
perturbs the inputs, re-solves, and reports the deltas.

**Why.** The use case asks for scenario analysis explicitly. Re-solving rather
than scaling the answer is what makes it real: under a supplier outage the plan
still meets demand in full and costs a few per cent more, which is the argument
for a broad approved base.

**Differently.** Stochastic optimisation over a distribution of futures, rather
than one deterministic re-solve per scenario.

### P2 — Demand forecast

**What.** LightGBM on lags 1–4, rolling means and standard deviations, price,
discount, competitor price and week of year. Chronological split, train to
2023-08-21.

**Why.** It beats seasonal naive by 24% relative (WAPE 0.340 vs 0.445) and a
moving average by 6%. Four of the top ten features are price and promotion
variables, which an ARIMA could not have used.

**Differently.** Quantile forecasts instead of a point forecast, so safety stock
uses the model's own uncertainty rather than a historical sigma.

### P2 — Cold start

**What.** For a style with no history, find the nearest analogue by category,
price band and launch timing, and scale its curve. Backtested by holding out a
real style entirely.

**Why.** WAPE 0.378 against 0.417 for a category average — a real improvement,
honestly measured on one held-out style, which we say out loud because one style
is a small test.

**Differently.** A time-series foundation model for the cold-start case. It is
recorded in the metrics file as not installed on the build machine; we chose a
method we could run offline.

### P2 — Safety stock

**What.** `z x sigma x sqrt(L)` per style-store, then a backtest over 2,722
style-weeks counting how often demand exceeded cover.

**Why.** Because the planned service level is an input and the achieved one is a
result. We planned 95% and achieved **96.8%**, which is the only version of that
sentence worth saying.

**Differently.** Uncertainty from the forecast model rather than historical
variance; and optimise the service level against the cost of a stockout instead of
fixing it at 95%.

### P2 — Production LP and fabric lot sizing

**What.** An LP across three plants respecting weekly capacity and changeover,
then Wagner-Whitin dynamic lot sizing on fabric against MOQ and a five-week lead
time.

**Why.** The use case names capacity and fabric lead times as the things the
merchandising plan collides with. Peak utilisation comes out at exactly 100%,
which is why the reconciliation gap exists at all.

**Differently.** Sequence-dependent changeovers, and a rolling horizon rather than
a single 13-week solve.

### P2 — Markdown

**What.** Compare in-season sell-through to plan, and for styles tracking behind,
recommend a markdown week and depth. Priced on **revenue with salvage**, not
margin.

**Why.** Two decisions to defend. First, once the buy is made the cost is sunk, so
the question is revenue against salvage value, not margin — repricing this changed
markdown from "never pays" to a 159 k recovery. Second, the elasticity: we fitted
it, it explained **0.0%** of the variation, so we use a published apparel figure of
−1.8 and label it "assumed" in the API, the metrics file and on the screen.

**Differently.** Fit elasticity properly on real promotional data. It is the first
thing we would fix given more data.

### P2 — S&OP reconciliation and cycle

**What.** Three plans side by side — merchandising, statistical forecast,
constrained supply — with the gap in units and money, and one agreed consensus
number that can be lowered by hand but never raised above supply. Five stages,
rolling monthly, versioned.

**Why.** This is the use case. The gap is 99,686 units and 5.56 M, and the cap on
the consensus is the discipline the meeting exists to enforce: a business can
decide to sell less than the plants can make, never more.

**Differently.** Multiple scenarios per cycle (optimistic, base, pessimistic) and
a proper approval workflow with roles.

### Cross-cutting — monitoring and the demo pack

**What.** Middleware times every request; `/api/monitoring` reports counts, error
rate and p50/p95 per endpoint. Every model is trained ahead of time by
`scripts/build_demo_pack.py`, every seed pinned at 42, and a test fails the build
if training code appears in an API module.

**Why.** "Real-time decisions" and "process of monitoring" are judging criteria,
and both are easier to claim than to show. This shows them, and it is small enough
that we can explain all 110 lines.

---

## 3. Questions we expect, with answers

### On the data

**"Is this real data?"**
Partly, and every screen says which. The 10,324 purchase orders in SupplyGuard are
real — the SCMS delivery history, a genuine health-commodity supply chain. The
retail dataset behind TrendWear is public *synthetic* data, labelled as such
everywhere. Supplier capacity, prices and the merchandising plan are generated by
us, with the method in `docs/assumptions.md`. Accuracy is measured on real rows
only.

**"Why generate data at all?"**
Because the real dataset has no quotes, no capacity and no approved supplier list,
and the use case requires allocating across suppliers with all three. The choice
was to generate them and say so, or to change the problem. We generated them, and
labelled every generated row.

**"Isn't the SAP dataset a real SAP export?"**
No — and we said so in an earlier version of our own brief, wrongly, then
corrected it. It is Google Cloud demo data. It gives us a realistic material and
plant master, nothing more.

### On the models

**"Your quality model is worse than the baseline. Why is it in the project?"**
It is in the project as evidence. We trained it, measured it against two baselines,
and it lost — PR-AUC 0.164 against 0.256. So the application does not use it: it
falls back to the supplier's observed quality rate and says "not sufficient" on the
Models screen. With 71 positive labels that is the correct outcome, and a gate that
would have passed it is a gate we would not trust anywhere else.

**"Why random forest over XGBoost?"**
Measured. PR-AUC 0.347 against 0.334, and much better recall at a usable threshold
— 0.375 against 0.088. All three candidates are in the metrics file and on screen.

**"How do you know you have no leakage?"**
Two things. Every split is chronological — delay trains to December 2013 and tests
on 2014–2015. And every supplier feature is built with `shift(1)` and expanding
windows, so a row cannot see its own outcome. The top feature is the supplier's
prior late rate, which is exactly the feature that would have leaked if we had been
careless.

**"Your calibration made it worse?"**
Yes. Isotonic calibration on the held-out period dropped PR-AUC from 0.345 to
0.231, below baseline, so we removed it. Cross-validated calibration inside the
training period was kept where it helped. We would rather report the experiment
than hide it.

### On the optimiser

**"What makes this better than buying from the cheapest supplier?"**
It costs 6.4% more on the invoice and 1.3 points less of the volume sits with
high-risk suppliers. Priced in expected shortage cost, the total is lower. And
cheapest-first cannot satisfy "at least two suppliers per material" and a 40%
concentration cap at the same time — it is not just worse, it is infeasible against
the policy.

**"What if it is infeasible?"**
It escalates: first raise the concentration cap, then waive contract minimums, and
it always reports what it relaxed. We hit genuine infeasibility four times during
the build — contract ceilings at 5%, ceilings tighter than the cap, MOQs derived
from bulk shipment sizes, and network capacity compared against per-plant
requirements — and fixed each at source rather than by loosening the model.

**"Eight seconds for eight plants. Does that scale?"**
Not to a real network, and we would not pretend it does. A few hundred plants and
thousands of materials needs decomposition, warm starts, or OR-Tools CP-SAT. That
is costed at 8 person-days in `docs/estimate-and-roadmap.md`.

**"Where do the risk prices come from?"**
Config constants — the cost of a late unit and the cost of a quality event. They
are the two numbers that decide how much extra the plan pays to avoid risk, and
any adopter must set them from their own cost of a stockout. We say this rather
than implying they are derived.

### On P2

**"Why is the consensus lower than both the forecast and supply?"**
Because it is capped per style and week, not in aggregate. A style can be
supply-short in week 3 and over-supplied in week 7, and the cap applies weekly. The
aggregate consensus is therefore below both totals, which is what a real
constrained commitment looks like.

**"Your elasticity is assumed. Doesn't that undermine the markdown engine?"**
It bounds it. The timing comes from measured sell-through against plan, which is
real. The depth uses an assumed elasticity because the data has no usable price
response — our fit explained 0.0% of the variation. The recommendation is directional
and the screen says so. Fitting a curve to noise would have been worse.

**"A 96.8% achieved service level against 95% planned — is that not just luck?"**
It is a backtest over 2,722 style-weeks with 87 breaches, so it is a measurement
rather than an anecdote. It is slightly conservative because sigma is computed on
history that includes promotional spikes.

### On engineering

**"Why no framework on the front end?"**
Thirteen screens of tables and charts, four people, one week, and a demo that must
work offline. No build step means nothing between the code and the page. The cost
is that we wrote our own sortable table; the benefit is that the app starts in
seconds and has no `node_modules`.

**"How would you monitor this in production?"**
Today: `/api/monitoring` gives per-endpoint counts, error rate and p50/p95, and
every response carries `X-Response-Time-Ms`. What is missing and costed:
input-drift and prediction-drift monitoring, an alert when live precision falls
below the published 0.41, and a model registry with rollback.

**"What is the weakest part of this project?"**
Supplier capacity. The optimiser is only as good as those numbers, and today they
are inferred from observed shipment rates rather than confirmed by suppliers. Every
result downstream inherits that assumption, which is why a supplier portal is in
Phase 3 and flagged as a risk to a sponsor.

---

## 4. What we volunteer before being asked

Four things. Saying them first is the difference between a prototype and a claim.

1. **P2's dataset is public synthetic data**, not real sales.
2. **The markdown elasticity is assumed**, because our fit explained nothing.
3. **Supplier capacity, prices and the merchandising plan are generated by us**,
   with the method written down.
4. **Two of the three risk models are not good enough to use**, so they are not
   used.

Every one of these is already printed on the screen it affects. That is the point:
the honesty is in the application, not just in the answer.
