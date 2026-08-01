"""Engine factory for the eval harness.

Mirrors `apps/data-pipeline/core/db.py` rather than importing it: a package under
`packages/python/` must not depend on an app. Every `store` function takes an
`Engine` explicitly, so callers that already have one (the data-pipeline jobs)
should pass theirs instead of building a second.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


def get_engine(database_url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine against the logging Postgres.

    Falls back to `DATABASE_URL` from the environment.
    """
    url_str = database_url or os.getenv("DATABASE_URL")
    if not url_str:
        raise RuntimeError("DATABASE_URL not set")

    url = make_url(url_str)
    # Prefer psycopg (v3, self-contained wheels) to avoid local libpq issues
    if url.drivername in ("postgresql", "postgresql+psycopg2"):
        url = url.set(drivername="postgresql+psycopg")

    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
    )