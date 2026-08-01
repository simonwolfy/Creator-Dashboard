from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from creator_intelligence.utils.paths import LOG_DIR

def configure_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        LOG_DIR / "creator_intelligence.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
