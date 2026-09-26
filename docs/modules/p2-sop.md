# P2 — S&OP reconciliation, cycle and financials

**What it does.** Puts three disagreeing plans side by side, prices the gap, and
records the one number the business commits to. Then wraps that in a rolling
monthly cycle with stages and versions, and reports what it means in money.

**Where it lives.** `apps/p2/backend/trendwear/sop/` — `reconcile.py`,
`cycle.py`, `financials.py`, `distribution.py`.

**Why it matters.** This *is* the use case. Everything else in TrendWear exists to
produce an input to this screen.

---

## The reconciliation

Three numbers exist for every style and week, and they rarely agree:

| Plan | What it is | Total |
|---|---|---|
| **Merchandising** | What the buyers intend to sell — a commercial ambition, **+16.1%** above the forecast, because a buyer who plans for the statistical average has already given up on the season | **696,148** units |
| **Statistical forecast** | What the data expects ([p2-forecast.md](p2-forecast.md)) | **599,528** units |
| **Constrained supply** | What the plants can actually make, after capacity and fabric lead times ([p2-planning.md](p2-planning.md)) | **652,062** units |

**The gap between the first and the third is the conversation the cycle exists to
have:** 100,618 units, **5.57 million** in revenue, across 34 styles that are
short.

The **consensus** is the single number the business commits to:
**595,530 units**.

### The one rule enforced in code

```
consensus = min(merchandising, supply)      per style, per week
```

Pre-S&OP may **lower** the consensus by hand. It may not **raise** it above what
supply can deliver — `override_consensus()` caps the value and records
`"agreed (capped at supply)"` when it does. A meeting can decide to sell less than
the plants can make; it cannot decide to sell more. That discipline is the point
of an S&OP cycle, so it lives in the code rather than in a comment.

### Why the consensus is below all three totals

The question a panel will ask, and the answer is precise: the cap applies **per
style and week**, not in aggregate. A style can be short in week 3 and
over-supplied in week 7; the shortfall is capped and the surplus is not credited
back. Summed, that puts the consensus below both the forecast total and the supply
total. It is what a genuinely constrained commitment looks like, and an aggregate
cap would have hidden it.

### Where the argument will be

`biggest_gaps()` orders styles by **gap value in money**, so the meeting knows
which four styles to spend its time on rather than reading 60 rows.

---

## The rolling cycle

**Five stages**, monthly, versioned: the cycle is a list in `cycle.py`, and each
run writes a version row with its stage, so a plan can be traced to the meeting
that agreed it.

Three cycles are generated so the screen shows a *rolling* process rather than a
single snapshot — the use case asks for "a rolling monthly S&OP cycle over sales,
production and inventory", and a one-shot plan would not answer it.

**What is missing, and costed.** No roles, no approval workflow, no audit of who
changed what. Version rows record the stage, not the person. That is 10
person-days in [../estimate-and-roadmap.md](../estimate-and-roadmap.md), and it is
not optional in a real deployment.

---

## Financials

The consensus translated into money, because an S&OP meeting that ends without a
financial number has not finished:

| | |
|---|---|
| Revenue | 32,921,710 |
| Cost of sales | 13,827,095 |
| Gross margin | **19,094,616** (58%) |
| Inventory value | 1,202,370 |
| Distribution cost | 470,468 |
| Lost sales value | 0 |
| Contribution | 18,624,147 |
| Units committed | 595,530 |

Also reported by category, so the screen answers "where is the margin" and not
only "how much".

**Lost sales are zero**, and that needs saying rather than glossing: the plan meets
the *forecast* in full. The 5.57 M gap is against merchandising *ambition*, which
is a different and larger number. Confusing the two would overstate the problem.

---

## Distribution

`distribution.py` covers the part of the use case that is easy to forget: **made is
not the same as on sale**. DC-to-store lanes carry a lead time and a cost per unit,
so a unit produced in week 6 is available to sell in week 7 or 8, and the
distribution cost (470,468) lands in the financials.

---

## Interfaces

- Consumes: `forecast`, the merchandising plan, the constrained supply plan,
  `styles`, `lanes`.
- Produces: `reconciliation` (`merch_units`, `forecast_units`, `supply_units`,
  `gap_units`, `gap_value`, `consensus_units`, `consensus_source`), `versions`,
  `availability`, and `metrics["financials"]`.
- `POST /api/reconciliation/consensus` is the override, capped as above.
- Screens: **Cockpit** (`/`), **Reconcile** (`/pages/reconcile.html`),
  **Logistics** (`/pages/logistics.html`).

## What we would do differently

- Three scenarios per cycle — optimistic, base, pessimistic — rather than one.
- A proper approval workflow with roles and an audit trail.
- Carry unconstrained demand forward as backlog instead of dropping it, so the gap
  accumulates across weeks the way a real shortfall does.
- Let the cycle close: today each cycle is generated, not *closed* with an actual
  against plan. Adding the close would make the rolling process complete.
