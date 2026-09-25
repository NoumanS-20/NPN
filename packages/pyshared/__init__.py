"""Plumbing shared by both applications: metrics, time splits and logging.

Deliberately free of domain logic — no suppliers, no styles, no planning rules.
A test in tests/test_separation.py enforces that.
"""

from pyshared.logging import get_logger
from pyshared.metrics import (
    classification_report_dict,
    compare_to_baseline,
    regression_report_dict,
)
from pyshared.timeutil import split_boundaries, time_split, to_week_start

__all__ = [
    "get_logger",
    "classification_report_dict",
    "compare_to_baseline",
    "regression_report_dict",
    "split_boundaries",
    "time_split",
    "to_week_start",
]
