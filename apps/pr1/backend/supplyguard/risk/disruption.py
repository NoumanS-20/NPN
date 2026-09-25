"""Predict whether an order will be cancelled or only partly delivered.

Label: order status of Cancelled or Partially Delivered — 136 of 777 orders,
17.5%. This is the "supplier disruption" the use case asks us to anticipate.

The file covers five suppliers whose disruption rates sit between 16.3% and
19.9%, so there is very little to separate them. The sufficiency gate in
``small_label`` decides whether a model ships or whether we fall back to the
observed rate and say so.
"""

from __future__ import annotations

import pandas as pd

from supplyguard.etl.procurement_files import DISRUPTION_FEATURES
from supplyguard.risk.base import TrainedModel
from supplyguard.risk.small_label import train_small_label

LABEL = "is_disrupted"
DATE_COLUMN = "order_date"
PRIOR_COLUMN = "supplier_prior_disruption_rate"


def train(orders: pd.DataFrame, test_fraction: float = 0.3) -> TrainedModel:
    return train_small_label(
        orders,
        name="disruption",
        label=LABEL,
        date_column=DATE_COLUMN,
        features=DISRUPTION_FEATURES,
        prior_column=PRIOR_COLUMN,
        test_fraction=test_fraction,
    )
