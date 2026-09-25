# PR1 — scenario analysis

**What it does.** Re-plans under a disruption and reports what it costs. The use case asks for "scenario
analysis for supplier disruptions or demand spikes", and this is the part of the demo the panel will drive.

**Where it lives.** `apps/pr1/backend/supplyguard/scenarios/engine.py`.

## How it works

Each scenario is a **pure transformation of the inputs**, followed by a fresh solve on the same optimiser.
Nothing about the model changes. Two consequences worth stating on stage:

- The before and after are genuinely comparable — same objective, same constraints.
- There is no separate "scenario mode" that could behave differently from the real planner.

A test asserts scenarios never mutate the inputs, so running one cannot corrupt the next.

## Measured results — 192 requirement lines, four-week horizon

Base plan: total cost 192,688, expected late units 119,641, 55 suppliers, 1.8% high-risk volume.

| Scenario | Result | Total cost | Expected late | High-risk | Suppliers |
|---|---|---|---|---|---|
| **Outage of the largest supplier** (110k units) | absorbed | **+2.7%** | −3.1% | +1.6pp | +1 |
| **Demand +30%** | absorbed | **+35.8%** | +34.1% | −0.1pp | 0 |
| **Lead time +2 weeks** | absorbed | +0.3% | +0.2% | 0.0pp | 0 |
| **Lead time +6 weeks** | **plan breaks** | — | — | — | — |
| **Price +25%** | absorbed | +25.0% | 0.0% | 0.0pp | 0 |

Each solve takes about 2.5 seconds, so the panel can change an input and watch it re-plan.

**The three findings worth narrating:**

1. **Losing the biggest supplier costs 2.7%, not a crisis.** 110,000 units move to other suppliers and the
   plan still meets demand in full. That is the argument for having qualified a broad approved base.
2. **A 30% demand spike costs 35.8%** — more than proportional, because the cheap capacity runs out first and
   the extra volume goes to dearer suppliers. Scarcity has a price and the model shows it.
3. **A six-week lead-time shock breaks the plan outright.** The app says so plainly rather than quietly
   producing a plan that could not be delivered. Knowing where the cliff is *is* the analysis.

## Choosing the lead-time allowance, honestly

Lead time only binds if the planning horizon is set to a real value. Risk-adjusted lead times here cluster
around 23 weeks with a tail past 30, which is normal for international pharmaceutical supply. We tested the
choice rather than guessing:

| Allowance | Base plan | +2 weeks | +6 weeks |
|---|---|---|---|
| 26 weeks | **infeasible** | — | — |
| **30 weeks** | optimal | +0.24% | **breaks** |
| 34 weeks | optimal | no effect | +0.24% |
| 40 weeks | optimal | +0.06% | +0.09% |

30 weeks is the setting where the plan is feasible and the scenario still has teeth.

**A bug worth owning:** the first version added 52 weeks of slack to the eligibility filter to avoid
infeasibility, which meant lead time never bound and the lead-time scenario moved **nothing at all** — 0.00%
on every metric. A scenario that changes nothing on screen is worse than not having one, and it would have
been noticed live.

## Likely questions

**Why does the outage make expected lateness go *down*?** Because the supplier we removed was a large one
with a middling risk score; the volume redistributes to suppliers that are, on average, slightly more
reliable. It costs 2.7% more and is marginally safer. That is a real trade and the app shows both sides.

**Why is the price shock exactly +25%?** Every supplier's price rises by the same amount, so there is nobody
cheaper to switch to. Targeting one country instead produces a smaller rise, because the optimiser then
substitutes away — that variant is in the app and is the more interesting demo.

**Could you add a scenario?** Yes — each one is a function that transforms inputs, about fifteen lines. A
currency shock or a quality failure at one plant would drop straight into the same structure.

**What happens when a scenario is infeasible?** The result carries the status, the reason, and a plain
sentence saying the approved base cannot absorb the disruption. We treat that as an answer, not a failure.
