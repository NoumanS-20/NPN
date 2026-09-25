# PR1 — supplier risk models

**What it does.** Predicts whether an order will go wrong *before* the purchase order is released. The
delay model is built; quality and disruption follow in Task 8.

**Where it lives.** `apps/pr1/backend/supplyguard/risk/` — `base.py` (shared machinery), `delay.py`.

**Why it matters.** The prediction does not sit in a report next to the plan. It enters the allocation
objective, so a supplier likely to be late costs more in the optimiser and receives less volume. That link —
model output to procurement action — is the thing to say on stage.

## Delay model — measured results

Trained on the earlier 75% of SCMS orders, tested on the later 25% (Dec 2013 – Dec 2015, 2,581 orders,
14.1% late).

| Model | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| **Random forest** (chosen) | **0.414** | **0.375** | **0.394** | **0.825** | **0.347** |
| XGBoost | 0.395 | 0.088 | 0.143 | 0.804 | 0.334 |
| Logistic regression | 0.260 | 0.838 | 0.397 | 0.774 | 0.287 |

| Baseline | PR-AUC |
|---|---|
| Supplier's own trailing late rate | 0.264 |
| Predict the overall rate for everything | 0.141 |

**The honest reading:** the model beats a planner with a spreadsheet by 0.08 PR-AUC, not by a landslide.
Say that plainly. It catches about 37% of late deliveries, and when it flags an order it is right about 41%
of the time, against a 14% background rate — roughly a threefold lift over guessing.

**Random forest won, and we kept it.** Selection prefers the simplest model within 0.01 PR-AUC of the best;
here logistic regression was 0.06 behind, which is a real gap, so the forest earned its place.

## Three decisions that materially changed the numbers

**1. Chronological split, never random.** Train on the past, test on the future. A random split lets the
model learn from orders placed after the ones it is scored on.

**2. Probabilities are calibrated.** The optimiser multiplies P(late) by shortage cost, so 0.3 has to mean
roughly three in ten. Class weighting — needed because positives are rare — pushes raw scores far above the
real rate. Isotonic calibration, cross-validated **within the training period only**, brings mean predicted
risk to 0.141 against an observed 0.115.

An earlier version calibrated on a single held-out slice of training data instead. It cost the model a fifth
of its training rows and dropped PR-AUC from 0.345 to **0.231 — below the baseline it is supposed to beat.**
Cross-validated calibration uses every training row and keeps discrimination intact.

**3. The threshold is chosen, not defaulted.** With 11.5% of orders late, a calibrated model almost never
exceeds 0.5, and at that default the model reported precision and recall of **exactly zero** while ranking
well. The threshold that maximises F1 over the *training* period (0.415) is applied unchanged to the test
period. The test data never influences the choice.

## What the model actually learned

| Feature | Importance |
|---|---|
| `supplier_prior_late_rate` | 0.211 |
| `destination_prior_late_rate` | 0.151 |
| `supplier_prior_volume` | 0.101 |
| `supplier_prior_orders` | 0.095 |
| `destination_prior_orders` | 0.092 |

Past behaviour dominates, for the supplier and for the destination — which is what a procurement professional
would expect, and a good sign that nothing strange is going on.

## Likely questions

**How do you know there's no leakage?** A test flips one order's outcome and asserts that order's own
features do not change. Every trailing feature is `shift(1)` then expanding, and the split is by date.

**Why is recall only 0.375?** Because precision matters here too: a false alarm moves volume away from a
supplier who would have delivered fine. The threshold sits where F1 is best on the training period. We can
raise recall on demand — logistic regression reaches 0.838 recall at 0.260 precision — and the panel can
see that trade-off in the benchmark table.

**Why not deep learning?** 10,324 rows and 19 tabular features. A neural network would have more parameters
than useful signal, and we could not explain a single prediction to a buyer.

**Is 0.347 PR-AUC good?** Against a 14% base rate and a 0.264 baseline, it is a real but modest improvement.
We would rather report that than dress it up.
