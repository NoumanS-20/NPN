# The front end

**What it is.** Plain HTML, CSS and JavaScript. No framework, no bundler, no build step. The browser loads
ES modules directly from `packages/web/`, and FastAPI serves them as static files.

**Where it lives.** `packages/web/` (shared) and `apps/*/web/` (each application's pages).

**How to run it.**

```bash
.venv/Scripts/python -m uvicorn supplyguard.main:app --port 8001 --app-dir apps/pr1/backend
.venv/Scripts/python -m uvicorn trendwear.main:app  --port 8002 --app-dir apps/p2/backend
cd packages/web && node --test tests/table.test.js tests/format.test.js
```

Node is used **only** to run tests. Nothing is compiled.

## Why no framework

The team decided this on 25 September, and the reason is the technical interview on the 30th: every member
can read plain JavaScript, and nobody can defend a framework they have not used. It is also literally what
the mentor's diagrams specify — "HTML + CSS + JS".

The practical consequences are good ones. There is no build to break the morning of the demo, no bundle to
rebuild after a last-minute fix, and the deployed container is Python only.

## What is shared

| File | Responsibility |
|---|---|
| `tokens.css` | Colour, type and spacing scales; light and dark |
| `base.css` | Layout, tables, panels, buttons, the split bar |
| `table.js` | Sortable, filterable, paginated table — about 150 lines, ours |
| `chart.js` | Chart.js wrappers and the allocation split bar |
| `api.js` | Fetch wrapper with loading, error and empty states |
| `format.js` | Every number that reaches a screen |

Each application supplies only its accent colour and its own pages. `packages/web` holds no domain logic, the
same rule the Python side follows.

## Three decisions worth defending

**1. Numbers are set in monospace with tabular figures.** In procurement the numbers *are* the content, and a
column of quantities has to be scannable down the page, not merely readable one at a time. This comes from
the subject — ledgers and purchase-order lines — rather than from a style preference.

**2. No web fonts.** The demo may run without a network. A page that falls back to Times because a font did
not load is worse than one that never asked. System stacks, tuned.

**3. The risk ramp is separate from the application accent.** Slate, amber and clay for low, medium and high
delay risk; navy for SupplyGuard and amber for TrendWear. A supplier's reliability must never be confused
with which app you are looking at — and the two accents make the applications distinguishable across a room
when they are demonstrated one after the other.

## The signature element: the allocation split bar

One bar per requirement. Each segment is a supplier: **width is their share, colour is their delay risk**,
and a diagonal hatch marks a generated supplier. Move the risk slider and the segments re-flow.

That is the argument of the entire project made visible. You do not read that risk changed the plan — you
watch volume move off the unreliable suppliers. Everything else on the page is deliberately quiet so that
this is the thing people remember.

## Small choices that came from testing

- **A numeric column opens best-first; a text column opens A–Z.** Clicking "On time" and seeing the worst
  supplier at the top would answer the wrong question. There is a test for it.
- **Missing values sort last in both directions.** A supplier with no on-time rate must never lead the
  reliability table.
- **Missing values render as an em dash, never as zero.** "0%" would say a supplier never delivers on time,
  which is the opposite of "we have no record".
- **An empty filter result says what was searched for.** A blank table looks like a bug.

## Performance, and why the overview loads instantly

`/api/kpis` solves the full plan and all three baselines — about eight seconds. It is computed once at
startup and cached for the life of the process, because the planning context never changes while the server
is up.

Measured after that change: KPIs **0.03 s**, supplier table **0.01 s**, a fresh allocation **0.6 s**. The
solve time is printed next to each result on screen, which is also our evidence for the "real-time decisions"
criterion.

## Accessibility and robustness

Keyboard focus is visible, sortable headers are focusable and respond to Enter and Space, the split bar
carries a text alternative, `prefers-reduced-motion` is respected, and the layout holds at 375 px with no
horizontal scroll. When the backend is unreachable the page says so rather than showing stale numbers — a
dashboard that quietly displays yesterday's figures is worse than one that admits it is offline.

## Likely questions

**Why write your own table?** Because the interview is on the 30th and a third-party grid is a dependency
nobody on the team has read. It is 150 lines, it is tested, and any of us can walk a panel through it.

**Is Chart.js not a framework?** It is a charting library, loaded from a local copy so the demo works
offline. The application structure is ours.

**How do the two apps stay separate on the front end too?** They share presentation primitives and nothing
else — no data, no state, no calls between them. The shared package contains no supplier, style, forecast or
allocation logic.

---

## The two screens the demo turns on

**Suppliers** (`/pages/suppliers.html`) — the comparison table. Every approved supplier with price, lead
time, delivery record, capacity, minimum order and predicted risk, filterable by material, plant and origin,
sortable on any column.

Two honesty markers a judge can see:
- A risk figure ending in `*` means we have **no trading history** with that supplier, so the number is the
  population average rather than a prediction about them.
- A lead time ending in `*` came from the supplier's **product group**, not their own record. Only 79 of 217
  suppliers have enough observations of their own.

**Allocation** (`/pages/allocate.html`) — the demo page. Plant, horizon and concentration cap on top; three
weight sliders below; then the split bars, the comparison against the alternatives, and every line with its
reason.

Measured on the running app, Nigeria, two weeks, 46 lines:

| Preset | Invoice | Expected late units | High-risk volume |
|---|---|---|---|
| Price only | ₹7,57,859 | 11,461 | 3.5% |
| Balanced | ₹7,58,625 (+0.1%) | 10,899 | 2.9% |
| Risk averse | ₹7,64,767 (+0.9%) | 10,683 (−6.8%) | **0.7%** |

The page narrates the change itself — *"+0.9% on the invoice, −6.8% expected late units"* — so nobody has to
read two numbers off a screen and subtract them in their head.

### Details that came out of using it

- **Requirement captions lead with the week.** Planning two weeks draws two bars per material, and without
  the week they looked like a duplicate rendering bug.
- **One legend per panel, not one per bar.** Repeated eight times down a page it buried what it explained.
- **Sliders debounce at 220 ms** and a stale response is discarded. A request per pixel of drag queues behind
  itself and makes a 0.2-second solver feel slow.
- **Static files are served `no-cache, must-revalidate`.** A browser kept an edited module from its cache
  during development; the same thing on 28 September, with a judge's tab open while we push a fix, would look
  like the app was broken.

---

## All thirteen screens

Six in SupplyGuard, seven in TrendWear Planner. Each one answers a question a
planner would actually ask, and each states the provenance of what it shows.

### SupplyGuard (PR1) — port 8001

| Screen | Heading | What it answers |
|---|---|---|
| `/` | *Buy on total cost, not on price* | The cockpit: total cost, invoice, suppliers used, high-risk share, and the comparison against how they actually bought |
| `/pages/suppliers.html` | *Who can supply this, and how well* | Every approved supplier with price, lead time, delivery record, capacity, MOQ and predicted risk |
| `/pages/allocate.html` | *Move the weights, watch the plan move* | The plan itself, with every line's reason and the three baselines |
| `/pages/risk-check.html` | *Check an order before it becomes a commitment* | Score one prospective order: delay, quality and disruption, with the reason in English |
| `/pages/scenarios.html` | *Break the plan on purpose* | Five disruptions, each re-solved, each with its delta |
| `/pages/models.html` | *Three risk targets. One supports a model.* | The bake-off, the baselines, and the sufficiency verdict per target |

### TrendWear Planner (P2) — port 8002

| Screen | Heading | What it answers |
|---|---|---|
| `/` | *One number the business commits to* | The cockpit: consensus, the gap in units and money, revenue, margin |
| `/pages/reconcile.html` | *Three plans, one agreed number* | Merchandising against forecast against supply, the gap priced, the override |
| `/pages/merchandising.html` | *What we expect to sell* | The forecast, its accuracy against baselines, and the cold-start method |
| `/pages/production.html` | *What the plants can actually make* | Capacity use, shortfalls, the production lines, and the fabric orders beneath |
| `/pages/logistics.html` | *Made is not the same as on sale* | DC-to-store lanes, lead times, and when units become available |
| `/pages/inventory.html` | *The price of being wrong* | Safety stock, and the achieved service level from the backtest |
| `/pages/markdown.html` | *Discount the ones that need it* | Recommendations by week and depth, with the elasticity labelled as assumed |

The headings are deliberately sentences rather than nouns. "Three risk targets.
One supports a model." tells a judge what the screen is *for* before they read a
single number, and it commits us to the honest reading in the one place we cannot
quietly drop it.

### One rule across all of them

**Nothing is shown without its provenance.** A generated supplier says generated. A
figure from a product group rather than a supplier's own record carries a marker.
An assumed elasticity says assumed. A model that failed its gate says so on the
screen that reports it. That rule is why the front end has as much text on it as it
does — and it is the reason we can point at a screen instead of confessing to a
caveat.
