# PR1 — baselines and the savings claim

**What it does.** Runs the three alternatives a procurement team would recognise, so our plan can be measured
against how buying is actually done rather than against nothing.

**Where it lives.** `apps/pr1/backend/supplyguard/optimizer/baselines.py`.

## The three alternatives

| Baseline | What it does | Why it is the right comparison |
|---|---|---|
| **Cheapest first** | Fill each requirement from the lowest price upward | What a spreadsheet does. On invoice cost alone it is optimal, so it is the hardest bar |
| **Equal split** | Divide each requirement evenly across approved suppliers | The "spread the risk" instinct, which spreads volume onto expensive and unreliable suppliers alike |
| **Historical mix** | Buy in the proportions the organisation used last year | The true status quo — what the money was actually spent on |

Every baseline respects capacity, because comparing against an impossible plan proves nothing. A test asserts
each one meets demand in full and stays within capacity; a baseline that quietly fell short would flatter us.

## Measured results — 192 requirement lines, four-week horizon

| | Invoice | Total cost | Expected late units | High-risk volume | Suppliers |
|---|---|---|---|---|---|
| **Our plan** | 111,516 | 192,102 | 119,279 | 1.8% | 62 |
| Cheapest first | 109,550 | 190,975 | 123,386 | 4.2% | 50 |
| Equal split | 130,066 | 224,977 | 122,620 | 6.0% | 90 |
| Historical mix | 133,777 | 238,208 | 131,730 | 3.4% | 37 |

**Against the status quo — the number for the deck:**

> **16.6% lower invoice, 19.4% lower total cost, 9.5% fewer expected late units**, against how this
> organisation actually bought last year.

## The honest caveat, which we state before anyone asks

Against **cheapest first** our plan costs **1.8% more on invoice and 0.6% more on total cost**. We do not
bury that.

The reason is not that the optimiser is weak: it is that the two plans obey different rules. Cheapest-first
ignores the concentration cap, the contract bands and the minimum supplier count. Our plan respects all
three, because they are sourcing policy, and the point of the policy is that the cheapest buy is not always
the buy you are allowed to make.

What the extra 0.6% buys, measured: **expected late units down 3.3%, and volume sitting on high-risk
suppliers down from 4.2% to 1.8%** — less than half. That is the trade, stated in both directions.

Said plainly on stage:

> "Against a pure cheapest-first buy we pay 0.6% more, and we cut high-risk volume by more than half while
> obeying sourcing rules cheapest-first ignores. Against how the organisation actually bought last year, we
> are 19% cheaper in total cost. Both numbers are in the app."

## Likely questions

**Why not compare against something you always beat?** Because a panel will ask what the hardest comparison
is, and a savings number with no losing case is not believable. Cheapest-first is the hardest bar and we
show it.

**Why does the historical mix cost so much more?** It concentrates volume on 37 suppliers chosen for reasons
the data does not record — relationships, contracts, convenience — and it pays 16.6% more per unit for it.

**Why does equal split use 90 suppliers and still do worse?** Spreading evenly means buying from expensive
and unreliable suppliers in the same proportion as good ones. Diversification without discrimination costs
14.3% and still leaves the highest high-risk share of any plan, at 6.0%.

**Are the baselines handicapped?** No, and the tests say so: each meets demand in full and respects capacity.
If anything they are advantaged, since they ignore the policy constraints our plan obeys.
