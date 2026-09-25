"""Predict whether an order will arrive with a quality problem.

Label: a material-discrepancy event on the order — 71 of 517 lines, 13.7%.

Source caveat stated up front: the file describing these orders says it is
synthetic, simulating a semiconductor manufacturer. Whatever we measure here
shows that the method works; it is not evidence about real suppliers. The
sufficiency gate in ``small_label`` decides whether a model ships at all.
"""

from __future__ import annotations

import pandas as pd

from supplyguard.etl.procurement_files import QUALITY_FEATURES
from supplyguard.risk.base import TrainedModel
from supplyguard.risk.small_label import train_small_label

LABEL = "has_quality_event"
DATE_COLUMN = "order_date"
PRIOR_COLUMN = "supplier_prior_quality_rate"


def train(orders: pd.DataFrame, test_fraction: float = 0.3) -> TrainedModel:
    return train_small_label(
        orders,
        name="quality",
        label=LABEL,
        date_column=DATE_COLUMN,
        features=QUALITY_FEATURES,
        prior_column=PRIOR_COLUMN,
        test_fraction=test_fraction,
    )
