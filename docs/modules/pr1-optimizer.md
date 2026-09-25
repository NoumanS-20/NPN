# PR1 — the allocation engine

**This is the module to know cold for 30 September.** It is PR1's core decision, and the one place where a
model's output changes what a business actually does.

**Where it lives.** `apps/pr1/backend/supplyguard/optimizer/` — `model.py`, `types.py`.
**Solver.** PuLP with CBC, both open source.

## What it decides

Given a requirement plan, a set of offers and a probability of lateness per supplier, choose **how much to buy
from whom, in which week**, at the lowest total cost.

## The objective, in words and in symbols

For each supplier *s*, material *m*, plant *p* and week *w*, choose a quantity and a yes/no order flag, and
minimise:

```
  w_cost    ×  price × qty                        the invoice
+ w_risk    ×  P(late)   × qty × shortage_cost    what lateness is expected to cost
+ w_quality ×  P(defect) × qty × rework_cost      what bad goods are expected to cost
```

Shortage cost is **3×** the item price, rework **1.5×**. Both are stated constants, visible and arguable,
rather than numbers buried in a formula. A late delivery of medicine costs far more than the medicine.

**The point:** risk is priced in money, so a planner can trade it against cost honestly instead of reading a
risk score printed beside a price and guessing. The three weights are the sliders on screen.

## The constraints

| # | Constraint | How |
|---|---|---|
| 0 | Approved suppliers only | By construction — unapproved combinations never become variables |
| 1 | Demand met exactly | `Σ qty = requirement` |
| 2 | Capacity | `qty ≤ capacity_per_week` |
| 3 | Minimum order quantity | `qty ≥ moq × order` and `qty ≤ M × order` |
| 4 | Contract ceilings | Supplier's total over the horizon ≤ `contract_max_share × material total` |
| 5 | Lead time | Risk-adjusted lead time must fit the week — applied as a filter, keeping the model small |
| 6 | Concentration cap | No supplier above `max_supplier_share` of a line |
| 7 | Minimum suppliers | At least *n* suppliers per line |

Constraint 3 is what makes this a **mixed-integer** problem rather than a linear one: the binary flag is
needed because "order nothing, or at least 500" is not a straight line.

## Measured results, 192 requirement lines across 8 plants

| Weighting | Invoice | Expected late units | High-risk volume | Solve |
|---|---|---|---|---|
| Cost only | 113,408 | 129,395 | 5.3% | 1.7 s |
| Balanced | +0.6% | **−4.9%** | 1.8% | 1.9 s |
| Risk-averse | +1.3% | **−6.9%** | **1.4%** | 1.9 s |

**The sentence for the panel:** *1.3% more on the invoice buys a 6.9% cut in expected late units and takes
high-risk volume from 5.3% to 1.4%.* That is the whole argument for risk-aware sourcing in one line, and it
comes out of the model rather than a slide.

Note what this table is and is not: it compares **our plan against itself** under three weightings, which is
what the sliders do on screen. The comparison against how buying is actually done — cheapest-first, equal
split and last year's mix — is in `pr1-baselines.md`, and it includes the case where we cost slightly more.

## When the rules contradict each other

Three limits apply to every supplier at once — capacity, the concentration cap and the contract ceiling — and
they can make a line impossible. Returning "infeasible" would tell a buyer nothing, so the engine escalates
the way a planner does, and **writes what it did onto the plan**:

1. Raise the concentration cap for that line (40% → 50% → 60% → 75% → 100%).
2. Only if that is still short, waive the contract ceilings and flag that the line needs an amendment.

Nothing is relaxed silently. `test_relaxations_are_never_silent` fails the build if it is.

## Four bugs found while building this, all of which would have shown on stage

| Symptom | Cause | Fix |
|---|---|---|
| Every plan infeasible | Contract ceilings averaged **5%** of volume, so six suppliers could cover 30% of demand | Ceilings floored above the concentration cap |
| Still infeasible | Contract ceilings of 25% bound tighter than the 40% cap — two substantial suppliers held to 116 units against a 464-unit need | A contract may not be tighter than the cap the planner works to |
| Every supplier ineligible | MOQ came from historical order quantities, which are **bulk shipments**: minimums of 573–3,117 against requirements of 640 | MOQ is 10% of weekly capacity, on the same weekly basis |
| 54 lines short | Capacity was network-wide (5,734/week) but requirements are per plant (640/week) | Capacity scaled by the plant's share of that material's demand |

Every one of them produced the same useless symptom — "infeasible" — from four different causes. The lesson
worth repeating in the interview: **an optimisation model is only as good as the units its inputs are
measured in.**

## Likely questions

**Why PuLP and not OR-Tools?** PuLP is a thin, readable layer over CBC, and every line of our model reads like
the mathematics. For a problem this size the solver time is identical, and we can explain it.

**Why is this integer and not linear?** Minimum order quantities. Without them it is a transportation problem
solvable by linear programming; with them each supplier has an on/off decision.

**How big does it get?** 192 lines × up to 8 eligible suppliers ≈ 1,500 continuous variables and as many
binaries. CBC solves it in under two seconds, which is what makes live re-planning possible.

**What if the panel asks for a constraint you don't have?** The structure takes one: each is four lines in
`model.py`. Adding "no more than two suppliers from one country" would go in beside the concentration cap.

**Why is `expected_late_units` so large?** It is units × probability summed over a four-week plan of 1.8
million units, not a count of late deliveries. It is a comparison number: what matters is that it falls 6.9%
between weightings.
