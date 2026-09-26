# P2 — markdown timing and depth

**What it does.** Compares in-season sell-through to plan and, for styles tracking
behind, recommends **which week** to mark down and **by how much**.

**Where it lives.** `apps/p2/backend/trendwear/markdown/` — `elasticity.py`
(the fit we rejected and the figure we use instead), `recommend.py`.

**Why it matters.** It is a named requirement of the use case, and it is the
module where we had to choose between a confident answer and an honest one.

**Measured.** 10 styles recommended for markdown, **159,000 in recovered
margin**.

---

## The elasticity, in full

This is the part to read carefully, because it is the thing we are most likely to
be challenged on.

**We fitted it.** A log-log regression of units on price across the real
style-weeks — the standard approach, and the right first move.

**It explains nothing.** R² = **0.0**, slope **+0.04** — the wrong sign and
effectively zero magnitude. The dataset contains no usable price response.

**So we do not use it.** The module falls back to a published apparel price
elasticity of **−1.8**, and the reason is recorded in the metrics file in plain
English:

> "the fitted response explains only 0.0% of the variation (slope 0.04), so it is
> too weak to plan with. Using the published apparel elasticity of −1.8, stated in
> the assumptions."

`metrics["elasticity"]["source"]` is the string `"assumed"`, the API returns it,
and the markdown screen prints it beside every recommendation.

**Why this is the right call.** Shipping the fitted curve would have produced
recommendations that look identical on screen and rest on noise. A judge cannot
tell those two apart by looking — which is exactly why the application has to say
which one it is. The timing logic is driven by measured sell-through, which is
real; only the depth depends on the assumption.

**What would fix it.** Real promotional data with genuine price variation. It is
the first thing on the list in
[../estimate-and-roadmap.md](../estimate-and-roadmap.md) Phase 3.

---

## The other decision: revenue with salvage, not margin

The first version of this module optimised margin, and concluded that **markdown
never pays** — which is obviously wrong, because every retailer marks down.

The error was economic, not arithmetic. Once the buy is made, **the unit cost is
sunk**. The real question at markdown time is: what do I get for this unit if I
discount it, against what I get if I do not sell it at all?

So the objective is **revenue with salvage value**, not margin:

```
value of marking down   = P(sell at the discounted price) × discounted price
                          + P(unsold) × salvage value
value of holding price  = P(sell at full price)           × full price
                          + P(unsold) × salvage value
```

Repricing on that basis turned "never" into a 159,000 recovery. The lesson is
worth stating in the interview: the model was fine and the objective was wrong,
and no amount of tuning would have found it.

---

## Timing

Depth is one half; **when** is the other, and the timing is the part that rests on
measured data.

For each style, each week: expected cumulative sell-through from the plan against
actual sell-through to date. A style behind plan by more than a threshold gets a
recommendation, and the recommended week is the earliest week at which acting
beats waiting — discount too early and margin is given away on units that would
have sold; too late and the season ends with stock in the warehouse.

## Interfaces

- Consumes: `forecast`, `styles`, `demand` (for actual sell-through), the
  production plan.
- Produces: `markdown` with `style_id`, `week`, `recommend`, `depth_pct`,
  `sell_through`, `sell_through_plan`, `value_uplift`; and
  `metrics["elasticity"]` carrying `value`, `source`, `r_squared` and `reason`.
- Screen: **Markdown** (`/pages/markdown.html`), which shows the elasticity source
  as a labelled caveat rather than a footnote.

## What we would do differently

- Fit elasticity on real promotional data, per category rather than one global
  figure.
- Model competitor price response — the dataset has a competitor price column and
  the forecast uses it, but the markdown module does not.
- Optimise markdown depth jointly across styles under a total-discount budget,
  which is how a real merchandising team is constrained.
- Treat salvage value as a parameter set by the business rather than a constant.
