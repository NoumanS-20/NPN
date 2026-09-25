# PR1 — plants, requirements, approved suppliers and offers

**What it does.** Turns purchase-order history into the four inputs the allocation engine consumes: the
plants we buy for, how much of each material each plant needs per week, which suppliers are approved to
supply it, and what each of those suppliers offers.

**Where it lives.** `apps/pr1/backend/supplyguard/etl/` — `plants.py`, `requirements.py`, `asl.py`,
`offers.py`.

## PR1 does not forecast — and a test enforces it

The official data spec lists a "material demand forecast (by SKU/plant)" as a PR1 *input*. We produce it as a
**deterministic roll-up of historical consumption with a seasonal index**, never a trained model.

Demand forecasting is P2's core method, and the mentor ruled in writing that the two solutions must not
overlap in approach. `test_pr1_contains_no_forecasting_model` scans this whole application and fails the
build if LightGBM, Chronos, Prophet, ARIMA or exponential smoothing ever appear here.

In a real system this is exactly how it works too: an MRP run hands procurement a requirement, and the buyer
can override it. Our requirement screen is editable for the same reason.

## What the numbers are

| Table | Size | Notes |
|---|---|---|
| Plants | 8 | The highest-volume destinations: Nigeria, Zambia, South Africa, Mozambique, Zimbabwe, Tanzania, Uganda, Côte d'Ivoire |
| Requirement plan | 384 lines | 16 materials × 8 plants × 8 weeks, 1.8 M units, median line 3,752 units/week |
| Approved supplier list | 326 approvals | 48 material-plant pairs, 6 to 11 suppliers each, 272 traded and 54 qualified |
| Offers | 326 | Price, lead time, weekly capacity and minimum order per supplier **and material** |

Only materials worth planning are included: a material must be at least 1% of a plant's volume, and each
plant plans its six largest. Otherwise the optimiser spends its time on single-unit lines no supplier would
quote against.

## Two ways onto the approved list

- **traded** — that supplier has actually delivered that material. Evidence, not assumption.
- **qualified** — a generated supplier cleared for materials in its own product group, added until the pair
  has at least six suppliers and enough capacity to cover the peak week. A procurement team does the same
  thing: when the approved base cannot cover demand, you qualify more suppliers.

Vendors from the SAP master are **never** approved. We have no trading history and no product classification
for them, so approving them would mean inventing a qualification that does not exist.

## The capacity story — worth knowing, because we got it wrong twice

Capacity had to be comparable to a weekly requirement, and two earlier versions were not:

| Version | Coverage (capacity ÷ peak weekly need) | Why it was wrong |
|---|---|---|
| Supplier-level quarterly volume | 245× to 11,844× | A quarterly total compared against a weekly need |
| Supplier-level weekly p95 | 86× to 3,212× | Capacity across *all* materials, compared against one material |
| **Sustainable weekly rate per supplier and material** | **1.6× to 63×, median 9×** | What we ship now |

With the first two, no constraint ever bound. The optimiser would have been "pick the cheapest row", minimum
order quantities and contract limits would have been decorative, and a supplier-outage scenario would have
changed nothing on screen — the worst possible outcome for a demo about risk-aware sourcing.

The fix: capacity is everything a supplier shipped **of that material**, divided by the weeks in the record,
doubled for headroom. Pharmaceutical procurement ships in bulk, so a supplier's best week can hold a
quarter's volume; a sustainable rate is directly comparable to the consumption the requirement is built from.

`test_capacity_is_not_so_large_that_it_stops_mattering` guards the scale so this cannot regress.

## Likely questions

**Where does the requirement come from?** Historical consumption per material and plant, averaged to a weekly
rate and shaped by a seasonal index built from week-of-year volume. It is an input, editable by the buyer.

**Why eight plants?** They are the eight highest-volume delivery destinations in the data. The mapping
delivery location → plant is stated openly; nothing is renamed to look like something it is not.

**How can a generated supplier be "approved"?** It is qualified for materials in its own product group, and
marked `qualified` rather than `traded` everywhere it appears, including on screen.

**What stops one supplier taking everything?** Three things: weekly capacity per material, the contract
maximum share, and the concentration cap in the optimiser. A single supplier can cover the average week for
most materials, so it is the concentration cap and contract bands that force a split — which is what happens
in real sourcing too.
