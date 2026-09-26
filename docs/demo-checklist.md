# Pre-demo checklist

Run this **on 27 September** and again **on the morning of the 28th**. It takes
about twenty minutes the first time and five the second.

The point of a checklist is that nobody has to remember anything under pressure.
Work down it in order and tick each line.

---

## 1. Rebuild the demo pack (27 September only)

```bash
python scripts/build_demo_pack.py
```

- [ ] SupplyGuard built without an error
- [ ] TrendWear Planner built without an error
- [ ] Final line reads `Demo pack ready.`

Then confirm without rebuilding:

```bash
python scripts/build_demo_pack.py --check
```

- [ ] Reads `Demo pack is ready: all 6 artifacts present and loadable.`

If anything is missing, the raw data is the usual cause:

```bash
python scripts/fetch_data.py --check
```

## 2. Tests green

```bash
python -m pytest -q
python -m ruff check .
cd packages/web && node --test
```

- [ ] Python suite passes
- [ ] ruff reports no issues
- [ ] JavaScript suite passes

A failing test on the morning of the demo is not a reason to skip the demo. It
is a reason to know which claim to stop making.

## 3. Both applications start, offline

Pull the network cable or turn Wi-Fi off first. Neither app needs a network once
the pack is built, and this is the only way to prove it.

```bash
python -m uvicorn supplyguard.main:app --port 8001
python -m uvicorn trendwear.main:app --port 8002
```

- [ ] SupplyGuard answers on <http://127.0.0.1:8001>
- [ ] TrendWear answers on <http://127.0.0.1:8002>
- [ ] Neither log shows a download, a model fit, or a timeout
- [ ] Startup finishes in under about fifteen seconds each

Turn the network back on afterwards.

## 4. Click every screen

**SupplyGuard (PR1)** — six screens:

- [ ] Cockpit: KPI tiles filled, no dashes
- [ ] Suppliers: table sorts, risk badges coloured
- [ ] Allocate: a plan solves and shows a solve time
- [ ] Risk check: a supplier returns three scores and a reason
- [ ] Scenarios: a scenario runs and the comparison fills
- [ ] Models: metrics and baselines shown, sufficiency stated

**TrendWear Planner (P2)** — seven screens:

- [ ] Cockpit: KPI tiles filled
- [ ] Reconcile: three lines on the chart, gap in units and money
- [ ] Merchandising: forecast and accuracy shown
- [ ] Production: capacity use and shortfalls
- [ ] Logistics: lanes and store availability
- [ ] Inventory: safety stock with the achieved service level
- [ ] Markdown: recommendations, with the elasticity caveat visible

## 5. Run the preloaded scenarios

Both apps ship two or three scenarios with the line to say written down, in
`apps/pr1/backend/supplyguard/demo/scenarios.py` and the matching P2 file.

SupplyGuard:

- [ ] **The monthly buy** — balanced weights, Nigeria, two weeks
- [ ] **Buying on price alone** — risk weight zero; high-risk volume rises
- [ ] **The biggest supplier goes down** — re-solves, demand still met in full

TrendWear:

- [ ] **The reconciliation** — the £5.6M gap, and what the consensus commits to
- [ ] **Markdown** — the recommendations, and the elasticity we could not measure

- [ ] Every solve returned in under about three seconds
- [ ] The numbers match what we rehearsed (they will: every seed is pinned)

## 6. Monitoring is live

- [ ] `GET /api/monitoring` on 8001 returns request counts and p95 latency
- [ ] Same on 8002
- [ ] `X-Response-Time-Ms` appears on a response header

This is the answer to "how would you monitor this in production", and it is
better shown than described.

## 7. The hosted copies are awake

Hugging Face Spaces sleep after inactivity and take 30–60 seconds to wake. Open
both about ten minutes before the slot:

- [ ] SupplyGuard Space loaded and answering
- [ ] TrendWear Space loaded and answering
- [ ] Laptop copies still running as the fallback

Demo from the laptop. The Spaces are the link we leave behind, not the thing we
present from — conference Wi-Fi decides otherwise too often.

## 8. The room

- [ ] Laptop charged and plugged in
- [ ] Both servers already running before we walk in
- [ ] All thirteen tabs already open, cockpit first
- [ ] Browser zoom at a size readable from three metres
- [ ] Notifications off, screen sleep off
- [ ] `docs/demo-script.md` open on a phone, not the laptop
- [ ] Printed one-pager of headline numbers, in case a screen dies

## 9. Know the four honest answers

Someone will ask. Have these ready, and do not dress them up:

- [ ] **P2's dataset is synthetic** — a public Kaggle synthetic retail set, said
      on the screen, not claimed as real sales.
- [ ] **Markdown elasticity is assumed** — we tried to fit it, it explained
      nothing, so it uses a published apparel figure and labels itself.
- [ ] **Supplier capacity and offers are generated** — the real dataset has no
      quotes or capacity in it; the method is in `docs/assumptions.md`.
- [ ] **Two of the three risk models are not sufficient** — too few positive
      labels, so they fall back to an observed rate and say so on the Models
      screen.

Volunteering these is the difference between a prototype and a claim. Every one
of them is already written on the screen it affects.
