"""Central logging setup for the CLI process."""

from __future__ import annotations

import logging


def configure_logging(level: str, log_format: str, verbose: bool) -> None:
    """Configure process logging once, keeping command output on stdout."""
    resolved_level: int | str = logging.DEBUG if verbose else level
    logging.basicConfig(level=resolved_level, format=log_format, force=True)
