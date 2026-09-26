# Demo script

Two demos, about four minutes each, for 28 September 2026.

Print this or keep it on a phone — not on the laptop, because the laptop is
showing the app. The click path is exact and the numbers are the ones the app
actually returns. If a number on screen differs from a number here, read the
screen: it is the same seed, but the plan you open may be a different slice.

**Before anyone speaks:** both servers already running, all thirteen tabs already
open, cockpits first. [demo-checklist.md](demo-checklist.md) covers the rest.

---

## Demo 1 — SupplyGuard (PR1) · four minutes

### 0:00 — The cockpit (`http://127.0.0.1:8001`)

Already open. Do not click anything yet.

> "This is SupplyGuard. It answers one question: given what eight plants need
> next month, which suppliers should we buy from? The headline is that this plan
> costs 20% less in total than the way this organisation actually bought last
> year, and 14% fewer units are expected to arrive late."

Point at the tiles: **total cost 474,910 · invoice 280,442 · 59 suppliers used ·
1.6% of volume on high-risk suppliers**.

> "The data underneath is 10,324 real purchase orders from a health-commodity
> supply chain, 520 suppliers, 16 materials. Where we had to generate something —
> capacity, prices — the row says so, and every accuracy number you will see is
> measured on real rows only."

### 0:50 — Suppliers (`/pages/suppliers.html`)

> "Every supplier, with its measured on-time and quality history, and the risk
> band we put it in."

Click a column header to sort by risk. Let them see it sort.

> "Approved supplier list, per material. The optimiser can only choose from here —
> which is the first constraint, and the one a spreadsheet usually forgets."

### 1:30 — Allocate (`/pages/allocate.html`) — **the moment**

Pick **plant-nigeria**, two weeks, balanced weights. Solve.

> "One month's buy for the largest plant. Solved in a quarter of a second, and
> every line says why that supplier was chosen."

Read one line aloud — they are all like this:

> "'Chosen despite a 32% price premium: delay risk is 10% lower than the cheapest
> supplier.' That trade is the whole product."

Now **set the risk weight to zero** and solve again.

> "Same demand, same suppliers, risk priced at nothing. The invoice gets cheaper
> and the volume sitting on high-risk suppliers roughly doubles. That difference is
> the argument for putting risk in the objective in money rather than in a report."

Set it back to 1.0 and solve once more, then scroll to the baseline comparison.

> "Three baselines, all solved, all shown. Against how they actually bought:
> 26.9% cheaper in total, 11.5% fewer expected late units. Against simply buying
> cheapest-first: we are 3.4% *dearer* on the invoice, and carry 1.9 points less
> high-risk volume. We show the baseline that beats us, because that is the number
> that makes the rest believable."

### 2:45 — Scenarios (`/pages/scenarios.html`)

Run **supplier outage**.

> "The supplier carrying the most volume stops delivering. It re-solves — demand
> is still met in full, cost goes up a few per cent. Nothing is retrained; the
> models are loaded at startup, which is why this is seconds and not minutes."

### 3:15 — Models (`/pages/models.html`) — **the honesty slide**

> "Three risk targets. One supports a model."

> "Delivery delay: random forest, PR-AUC 0.347 against a 0.264 baseline, ROC-AUC
> 0.825 on 2,581 held-out orders, chronologically split. We ship it."

> "Quality events and disruptions: both failed. 71 and 136 positive labels. The
> quality model scores *below* its own baseline. So the application does not use
> them — it falls back to each supplier's observed rate, and this screen says
> 'not sufficient' and gives the reason. We would rather show you a gate that
> rejected two of our own models than a dashboard of three green ticks."

### 3:45 — Close

> "Everything you have seen runs offline from a laptop. There is a hosted copy, a
> full test suite, and the documentation includes what we did *not* build — the
> ERP read and write paths, authentication, retraining — costed in person-days."

---

## Demo 2 — TrendWear Planner (P2) · four minutes

### 0:00 — The cockpit (`http://127.0.0.1:8002`)

> "TrendWear is a different problem and a separate application — no shared data,
> no shared models, no shared code. A test in the repository fails the build if
> one imports the other."

Point at the tiles: **consensus 595,530 units · gap 100,618 units worth 5.57
million · revenue 32.9 M · margin 58%**.

> "This is one monthly sales-and-operations planning cycle. The job is to turn
> three disagreeing plans into one number the business commits to."

### 0:40 — Reconcile (`/pages/reconcile.html`) — **the moment**

> "Three plans. Merchandising wants to sell 696,000 units — buyers plan 16% above
> the statistical forecast, because a buyer who plans for the average has already
> given up on the season. The forecast says 600,000. The plants can make 652,000."

Point at the three lines on the chart.

> "The gap between what the buyers want and what the plants can make is 100,618
> units — 5.57 million in revenue. That gap *is* the S&OP meeting."

Scroll to the biggest gaps table.

> "Ordered by money, so the meeting knows which four styles to argue about."

Now change a consensus number upward, deliberately.

> "I will try to commit to more than supply allows. It caps me. A meeting can
> decide to sell less than the plants can make; it cannot decide to sell more.
> That discipline is the point of the cycle, so it is enforced in code, not in a
> comment."

### 1:50 — Merchandising (`/pages/merchandising.html`)

> "Where the forecast comes from. LightGBM on lags, rolling statistics, price and
> discount. WAPE 0.340 against 0.445 for seasonal naive — 24% better than the
> baseline, on a chronological split."

> "And for a style with no history at all, a nearest-analogue method: 0.378
> against 0.417 for a category average, backtested by holding out a real style
> completely."

### 2:20 — Production (`/pages/production.html`)

> "Three plants, weekly capacity, changeover. Peak utilisation is exactly 100% —
> which is *why* the gap on the previous screen exists. Zero shortfall: the plan
> is feasible, it is just smaller than the ambition."

Mention fabric briefly:

> "Behind this, fabric is lot-sized with Wagner-Whitin against minimum order
> quantities and a five-week lead time, because fabric is what actually stops you
> making a style."

### 2:50 — Inventory (`/pages/inventory.html`)

> "Safety stock, z-sigma-root-L, planned at a 95% service level. Backtested over
> 2,722 style-weeks: **96.8% achieved**. The planned number is an input; the
> achieved number is the one worth quoting."

### 3:15 — Markdown (`/pages/markdown.html`) — **the honesty slide**

> "Ten styles are behind their sell-through plan, so each gets a recommended
> markdown week and depth, worth about 159,000 in recovered margin."

> "One thing to be straight about. We tried to fit the price response from this
> data. It explains 0.0% of the variation. So the depth uses a published apparel
> elasticity of −1.8, and the screen says 'assumed' — here."

Point at the label.

> "The timing is measured. The depth is assumed. We would rather show you the
> assumption than a curve fitted to noise."

### 3:45 — Close

> "One more thing worth showing —"

Open `/api/monitoring`.

> "Every request is timed. Counts, error rate, p50 and p95 per endpoint, live,
> while you have been clicking. 'Real-time decisions' and 'monitoring' are on the
> judging list, so we would rather show them than describe them."

---

## Recovery

| What breaks | What you do |
|---|---|
| A solve takes too long | Keep talking — the solve time prints when it lands. If over ten seconds, cancel, narrow to one plant and two weeks, and say the full network is nine seconds. |
| A screen is blank, API fine | Ctrl+Shift+R. Both apps send no-cache headers on front-end paths, so this is rare. |
| A server has died | The other tab still works. Restart in a terminal (`uvicorn ... --port 8001`); it is back in fifteen seconds. Fill the time with the Models screen on the other app. |
| "Infeasible" | Say what it is: the constraint set is tight for that slice. Narrow it, re-solve, and point out the relaxation ladder reports whatever it waives. Do not click the same button twice hoping. |
| A Space is asleep | Ignore it. The demo is the laptop; the Space is the link we leave behind. |
| No network at all | Nothing changes. Both apps run entirely offline — say so, because it is a feature. |
| A number contradicts this script | Read the screen, not the script. Every seed is pinned, so the app is right and the slice is different. |

---

## The four things to say without being asked

If they come up naturally, say them there. If not, say them in the close.

1. P2's dataset is public **synthetic** data, not real sales.
2. The markdown **elasticity is assumed**, because our fit explained nothing.
3. Supplier **capacity, prices and the merchandising plan are generated** by us.
4. **Two of the three risk models are not good enough to use**, so they are not
   used.

Every one is already printed on the screen it affects — point at it rather than
confessing it. That is the difference between a caveat and a design decision.
