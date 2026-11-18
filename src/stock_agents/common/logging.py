"""Project-wide logging. One rotating file per process + stderr."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_CONFIGURED: dict[str, bool] = {"done": False}
_FMT = "%(asctime)s %(levelname)s %(name)s | %(message)s"


def configure(level: str = "INFO", log_dir: str | os.PathLike | None = None) -> None:
    """Install root handlers (stderr + rotating file). Safe to call repeatedly."""
    if _CONFIGURED["done"]:
        return
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(_FMT))
    root.addHandler(stream)
    if log_dir:
        p = Path(log_dir)
        p.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            p / "stock-agents.log",
            maxBytes=50 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(fh)
    _CONFIGURED["done"] = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger. Lazily configures root on first call."""
    if not _CONFIGURED["done"]:
        configure()
    return logging.getLogger(name)
