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

---

# Quality and disruption — the labels did not hold up

The team agreed on 25 September not to promise three models until the labels were verified. They were
verified, and **two of the three did not survive**. This section is the evidence, and it is worth presenting
rather than hiding: knowing when not to ship a model is a result.

## What we measured

| Target | Rows | Positives | PR-AUC | Best baseline | ROC-AUC | Verdict |
|---|---|---|---|---|---|---|
| Delivery delay | 10,324 | 1,186 (11.5%) | **0.347** | 0.264 | **0.825** | **Ships** |
| Quality event | 517 | 71 (13.7%) | 0.164 | **0.256** | 0.592 | Falls back |
| Disruption | 777 | 136 (17.5%) | 0.192 | 0.193 | **0.482** | Falls back |

- **Quality**: the model scores *below* the supplier's own trailing rate. A planner with a spreadsheet does
  better, so shipping the model would make the system worse and harder to explain.
- **Disruption**: ROC-AUC of 0.482 is worse than a coin toss. The reason is visible in the data — across the
  five suppliers in that file, disruption rates run 16.3%, 16.8%, 16.9%, 17.3%, 19.9%. There is essentially
  nothing to separate them, so there is nothing for a model to learn.

## The sufficiency gate

A label supports a model only when, on the held-out later period, it beats the better of its two baselines by
at least **0.03 PR-AUC** and reaches **ROC-AUC ≥ 0.58**. Otherwise the module records the failure and the
estimator falls back to the **supplier's observed rate**.

The gate is deliberately strict. The failure it prevents — a confident-looking number with nothing behind it,
in front of a panel who will ask — is far worse than the failure it causes, which is a simpler input that is
plainly labelled.

The fallback is not a placeholder. Using a supplier's observed defect and disruption rate is what procurement
teams already do, it still feeds the optimiser's quality penalty, and it makes no claim to be a prediction.

## What we say on stage

> "We built three risk targets. One is a real model: delivery delay, ROC-AUC 0.825, beating the
> supplier-history baseline. The other two labels did not support a model — quality scored below its own
> baseline, and disruption came out worse than chance because the five suppliers in that file are
> indistinguishable. So for those we use the observed rate and label it as such. We would rather show you
> the gate that caught it than a number we could not defend."

## Likely questions

**Why not tune harder until they work?** Because the honest constraint is data, not effort. 517 rows with 71
positives across 44 suppliers cannot support a model that generalises, and tuning against the test set until
it passes is how you produce a number that fails in production.

**Would more data fix it?** Probably, for quality: the signal by component category (11.5% to 19.3%) suggests
something real, just not enough of it. For disruption, the five suppliers genuinely behave alike in this file.

**Does the optimiser suffer?** No. It consumes a probability either way. The delay model's calibrated
prediction and the observed quality rate both enter the objective; only one of them claims to be a
prediction.
