from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from creator_intelligence.utils.paths import LOG_DIR


def configure_logging(log_dir: Path | None = None, level: int = logging.INFO) -> None:
    target = Path(log_dir or LOG_DIR)
    target.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)

    marker = "creator_intelligence_managed"
    if not any(getattr(handler, marker, False) for handler in root.handlers):
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        file_handler = RotatingFileHandler(
            target / "creator_intelligence.log",
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        console_handler = logging.StreamHandler()
        for handler in (file_handler, console_handler):
            setattr(handler, marker, True)
            handler.setFormatter(formatter)
            root.addHandler(handler)

    # Third-party libraries can emit thousands of informational lines while
    # rendering dashboards. Keep warnings and errors without hiding failures.
    for noisy_logger in (
        "matplotlib",
        "matplotlib.category",
        "PIL",
        "fontTools",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
