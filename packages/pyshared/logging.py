"""One logger configuration for both applications."""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_configured = False


def configure(level: str | None = None) -> None:
    """Configure root logging once. Level comes from ``LOG_LEVEL`` or defaults to INFO."""
    global _configured
    if _configured:
        return
    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)
