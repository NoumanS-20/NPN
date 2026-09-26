# P2 — inventory, production and fabric

Three modules that turn a forecast into something the plants can actually do.

**Where they live.** `apps/p2/backend/trendwear/inventory/safety_stock.py`,
`production/plan.py`, `fabric/lotsize.py`.

---

## Safety stock

**What it does.** Sets a stock buffer per style-store from demand variability and
replenishment lead time, then **measures whether it worked**.

**Method.** `safety stock = z × σ × √L`, with σ the weekly demand standard
deviation, L the lead time in weeks, and z the normal quantile for the target
service level (1.645 at 95%).

**Measured.** Planned at a 95% service level. Backtested over **2,722
style-weeks**: demand exceeded cover in **86** of them, a breach rate of 3.2% —
an **achieved service level of 96.8%**, holding 52,054 units.

**Why the backtest is the point.** The planned service level is an input: anyone
can type 95. The achieved level is a result, and it is the only version of the
sentence worth quoting. Ours comes out slightly conservative, and we know why: σ
is computed on history that includes promotional spikes, so the buffer is sized
for a volatility that is partly explained by discounts the forecast already knows
about.

**Differently.** Take σ from the forecast model's own residuals, or better, from
quantile forecasts. And optimise the service level against the cost of a stockout
rather than fixing it at 95% — a style with 54.5% margin and one with 20% do not
deserve the same buffer.

---

## Production plan

**What it does.** Decides which plant makes which style in which week, respecting
weekly capacity and changeover, to meet the forecast as fully as possible.

**Method.** A linear programme (PuLP + CBC): minimise production cost plus a
penalty on unmet demand, subject to weekly capacity per plant, changeover
allowance, and no production before a style's launch week.

**Measured.** 3 plants, 13 weeks, **660,350 units**, **peak utilisation 100%**,
**zero shortfall**, solved in **0.2 seconds**, status optimal.

**Why 100% matters.** It is not a coincidence, it is the calibration described in
[p2-etl.md](p2-etl.md): capacity is set so the constraint binds. That is what
creates the reconciliation gap on the screen the whole use case is about. A
capacity constraint with slack would have made every other screen less
interesting and taught a panel nothing.

**Zero shortfall, honestly.** The plan meets the *forecast* in full. It does not
meet the *merchandising ambition* — that is the 102,318-unit gap in
[p2-sop.md](p2-sop.md). Those are two different statements and it is worth being
precise about which one this module makes.

**Differently.** Sequence-dependent changeovers (making a coat after a shirt costs
more than after another coat), a rolling horizon rather than one 13-week solve,
and overtime as a decision variable with its own cost rather than a fixed capacity
ceiling.

---

## Fabric lot sizing

**What it does.** Decides when to order each fabric and how much, given a minimum
order quantity and a five-week lead time.

**Method.** **Wagner-Whitin** dynamic lot sizing — the exact dynamic-programming
solution to the trade-off between ordering cost and holding cost over a finite
horizon — with the MOQ applied to each order and the lead time offsetting the
order week from the requirement week.

**Why this and not a rule of thumb.** Economic order quantity assumes steady
demand, and an apparel season is the opposite: demand arrives in launch waves.
Wagner-Whitin handles time-varying demand exactly, it is fast at this size, and it
is a named textbook method a panel can look up — which matters more than novelty
when four people have to defend it.

**Why fabric is its own module.** The use case names fabric lead times as one of
the two things the merchandising plan collides with. Fabric is the real
constraint: a style cannot be made early because the cloth is not there, and a
five-week lead time means the decision is taken five weeks before anyone knows
whether the style is selling.

**Differently.** Fabric is currently single-sourced per material with a fixed
lead time. Multi-sourcing, and lead times that vary by supplier, would make it
more realistic — but allocating across suppliers is PR1's job, and the separation
rule says this application does not do that. Recording that boundary is more
useful than blurring it.

---

## Interfaces

- Consumes: `forecast`, `styles`, `capacity`, `bom`, `fabrics` from upstream.
- Produces: `inventory` (with `flag`), `production`, `capacity_use`,
  `shortfalls`, `fabric_orders`, and `metrics["safety_stock"]`,
  `metrics["production"]`.
- Screens: **Inventory** (`/pages/inventory.html`), **Production**
  (`/pages/production.html`), with the fabric orders shown beneath production.
