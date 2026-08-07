from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from creator_intelligence.utils.paths import LOG_DIR


class SensitiveDataFilter(logging.Filter):
    PATTERNS=(
        (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),r"\1[REDACTED]"),
        (re.compile(r"(?i)(access_token|refresh_token|api_key|client_secret|password|authorization_code)(\s*[=:]\s*)[^\s,;]+"),r"\1\2[REDACTED]"),
        (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),"[REDACTED]"),
        (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),"[REDACTED]"),
    )
    @classmethod
    def redact(cls,value):
        text=str(value)
        for pattern,replacement in cls.PATTERNS:
            text=pattern.sub(replacement,text)
        return text
    def filter(self,record):
        record.msg=self.redact(record.msg)
        if record.args:
            record.args=tuple(self.redact(value) for value in record.args) if isinstance(record.args,tuple) else self.redact(record.args)
        return True


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
            handler.addFilter(SensitiveDataFilter())
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


def shutdown_logging() -> None:
    """Close only handlers installed by Creator Intelligence."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if not getattr(handler, "creator_intelligence_managed", False):
            continue
        root.removeHandler(handler)
        handler.close()
