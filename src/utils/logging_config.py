"""Central logging setup.

The pipeline previously used bare `print()` calls and `except Exception: pass`,
which destroyed every diagnostic. Providers now log through the standard
`logging` module so failures are visible and levels are controllable.
"""

import logging
import os
import sys

_CONFIGURED = False

# Written to by setup_logging so the CLI can print a synthetic-data banner.
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: str | int | None = None) -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # These libraries are extremely chatty at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "yt_dlp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Module-level logger accessor; ensures configuration has happened."""
    setup_logging()
    return logging.getLogger(name)
