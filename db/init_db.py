"""Deprecated compatibility helpers; target databases are never initialized or seeded."""

from __future__ import annotations

import logging

import sqlalchemy as sa

from config.settings import Settings

LOGGER = logging.getLogger(__name__)
engine = None
metadata = sa.MetaData()


def init_db() -> None:
    """Keep the old entry point without creating or changing target tables."""
    LOGGER.info("Database DDL is disabled; the application only introspects the configured schema")


def seed_data() -> None:
    """Refuse writes; demo data must be provisioned outside this read-only app."""
    raise RuntimeError("The text-to-SQL application does not create or seed target databases.")


def get_revenue_definition() -> str:
    """Load domain-specific metric definitions from optional hints.md, if present."""
    from pathlib import Path

    try:
        return Path("hints.md").read_text(encoding="utf-8").strip()
    except OSError:
        return "No domain metric definitions are configured."
