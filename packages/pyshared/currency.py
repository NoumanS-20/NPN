"""One place that decides what a money figure means.

Both applications report in Indian rupees, because that is the audience. The
underlying data is not:

* **SupplyGuard (PR1)** reads the SCMS delivery history, which is real
  USAID-funded procurement and is denominated in **US dollars**. Those amounts
  are converted here. Relabelling them as rupees without converting would
  overstate nothing and understate everything by a factor of eighty-three, and
  it is the sort of thing a reviewer checks.
* **TrendWear Planner (P2)** uses a synthetic retail set whose prices are in no
  real currency at all. They are scaled by the same factor so that a shirt costs
  a plausible number of rupees rather than an implausible one.

The rate is a stated assumption, not a live lookup. A demo that changed its own
numbers depending on the day's exchange rate would be impossible to rehearse.
Change it here and rebuild; nothing else needs to know.
"""

from __future__ import annotations

# Rupees per US dollar. One number, one place, quoted in docs/assumptions.md.
USD_TO_INR = 83.0

# What every screen and every document should call the currency.
CURRENCY_CODE = "INR"
CURRENCY_SYMBOL = "₹"


def to_rupees(amount: float) -> float:
    """Convert a US dollar amount to rupees at the stated rate."""
    return amount * USD_TO_INR
