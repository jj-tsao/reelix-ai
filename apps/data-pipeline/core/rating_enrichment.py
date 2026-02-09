import io
import logging
import time
from typing import Mapping, Sequence

import httpx
import pandas as pd
from qdrant_client.http.exceptions import UnexpectedResponse
from core.config import (
    IMDB_RATINGS_URL,
    OMDB_API_KEY,
    QDRANT_API_KEY,
    QDRANT_ENDPOINT,
)
from reelix_core.config import (
    QDRANT_MOVIE_COLLECTION_NAME,
    QDRANT_TV_COLLECTION_NAME,
)
from core.vectorstore_pipeline import connect_qdrant
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

OMDB_URL = "https://www.omdbapi.com/"


# == Sync IMDb ratings dataset into imdb_ratings_raw ==
def sync_imdb_dataset(engine: Engine) -> None:
    """
    Download IMDb title.ratings.tsv.gz and atomically replace imdb_ratings_raw using a staging table + swap pattern.
    """
    logger.info("Downloading IMDb ratings dataset...")
    resp = httpx.get(IMDB_RATINGS_URL, timeout=60)
    resp.raise_for_status()

    raw_bytes = io.BytesIO(resp.content)
    df = pd.read_table(
        raw_bytes,
        compression="gzip",
        sep="\t",
        dtype={"tconst": "string", "averageRating": "float32", "numVotes": "int32"},
    )

    df = df.rename(
        columns={
            "averageRating": "average_rating",
            "numVotes": "num_votes",
        }
    )

    logger.info(
        "Loaded %d IMDb ratings rows into DataFrame, writing to staging table...",
        len(df),
    )

    staging_table = "imdb_ratings_raw_new"

    # 1) (Re)create staging table
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))
        conn.execute(
            text(
                f"""
                CREATE TABLE {staging_table} (
                  tconst         text PRIMARY KEY,
                  average_rating numeric(3,1),
                  num_votes      integer
                );
                """
            )
        )

    # 2) Bulk insert into staging table (separate transaction(s) under the hood)
    df.to_sql(
        staging_table,
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=20_000,
    )

    logger.info("Staging table %s loaded, swapping into place...", staging_table)

    # 3) Table swap: drop old, rename staging -> live
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS imdb_ratings_raw"))
        conn.execute(
            text(
                f"""
                ALTER TABLE {staging_table}
                  RENAME TO imdb_ratings_raw;
                """
            )
        )

    logger.info(
        "Swapped imdb_ratings_raw_new into imdb_ratings_raw. Creating indexes..."
    )

    # 4) Create indexes on the new live table
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_imdb_ratings_num_votes
                ON imdb_ratings_raw(num_votes);
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_imdb_ratings_avg_rating
                ON imdb_ratings_raw(average_rating);
                """
            )
        )

    logger.info("imdb_ratings_raw refreshed via staging + swap (old table dropped).")


# == Upsert media_ratings from media_ids + imdb_ratings_raw ==
def upsert_media_ratings_from_imdb(engine: Engine) -> None:
    logger.info("Upserting media_ratings from imdb_ratings_raw...")

    sql = text(
        """
        INSERT INTO media_ratings AS mr (media_type, tmdb_id, imdb_id, release_date, imdb_rating, imdb_votes, updated_at)
        SELECT
          mi.media_type,
          mi.tmdb_id,
          mi.imdb_id,
          mi.release_date,
          ir.average_rating,
          ir.num_votes,
          now()
        FROM media_ids mi
        LEFT JOIN imdb_ratings_raw ir
          ON mi.imdb_id = ir.tconst
        WHERE mi.imdb_id IS NOT NULL
        ON CONFLICT (media_type, tmdb_id) DO UPDATE
          SET imdb_id      = EXCLUDED.imdb_id,
              release_date = EXCLUDED.release_date,
              imdb_rating  = EXCLUDED.imdb_rating,
              imdb_votes   = EXCLUDED.imdb_votes,
              updated_at   = now()
        WHERE mr.imdb_rating IS DISTINCT FROM EXCLUDED.imdb_rating
          OR mr.imdb_votes  IS DISTINCT FROM EXCLUDED.imdb_votes;
        """
    )

    with engine.begin() as conn:
        conn.execute(sql)

    logger.info("media_ratings updated with IMDb ratings.")


# == OMDb for RT, Metacritics, and awards (daily & weekly) ==
def fetch_from_omdb(
    imdb_id: str,
) -> tuple[int | None, int | None, str | None, str]:
    """
    Call OMDb by IMDb ID and extract:
      - Rotten Tomatoes score (0–100) if present
      - Metascore (0–100) if present
      - Awards summary string (may be None)
    Returns:
      (rt_score, metascore, awards_summary, omdb_status)
    where omdb_status ∈ {"ok", "not_found", "error"}.
    """
    params = {"apikey": OMDB_API_KEY, "i": imdb_id}

    try:
        resp = httpx.get(OMDB_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("HTTP error for imdb_id=%s: %s", imdb_id, e)
        return None, None, None, "error"

    if data.get("Response") != "True":
        err = (data.get("Error") or "").lower()
        logger.info("OMDb: no data for %s: %s", imdb_id, data.get("Error"))

        if "not found" in err or "incorrect imdb id" in err:
            return None, None, None, "not_found"

        # Other OMDb-side issues → treat as transient error
        return None, None, None, "error"

    # Rotten Tomatoes
    rt_score: int | None = None
    for rating in data.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            value = rating.get("Value")  # e.g. "87%"
            if value and value.endswith("%"):
                try:
                    rt_score = int(value.rstrip("%"))
                except ValueError:
                    rt_score = None
            break

    # Metascore
    metascore: int | None = None
    metascore_raw = data.get("Metascore")
    if metascore_raw and metascore_raw != "N/A":
        try:
            metascore = int(metascore_raw)
        except ValueError:
            metascore = None

    if metascore is None:
        # Fallback: parse from Ratings array if Metascore field missing
        for rating in data.get("Ratings", []):
            if rating.get("Source") == "Metacritic":
                value = rating.get("Value")  # e.g. "65/100"
                if value and "/" in value:
                    num = value.split("/", 1)[0]
                    try:
                        metascore = int(num)
                    except ValueError:
                        metascore = None
                break

    awards: str | None = data.get("Awards") or None

    return rt_score, metascore, awards, "ok"


def select_daily_omdb_candidates(
    engine: Engine,
    limit: int = 1000,
    recent_months: int = 3,
    min_votes: int | None = 200,
) -> Sequence[Mapping]:
    """
    DAILY selector — focused exclusively on recent releases.

    All tiers are scoped to titles released within `recent_months`.
    Catalog-wide sweeps are left to the weekly pipeline.

    Priority:
      0) Recent + never checked (omdb_status IS NULL)
      1) Recent + error (transient failure, retry after 1 day)
      2) Recent + has RT score (refresh after 7 days)
      3) Recent + not_found (retry after 14 days)
      99) Everything else (skip — weekly handles it)
    """
    vote_filter = ""
    params: dict = {"limit": limit}

    if min_votes is not None:
        vote_filter = "AND (imdb_votes IS NULL OR imdb_votes >= :min_votes)"
        params["min_votes"] = min_votes

    sql = text(
        f"""
        SELECT
            media_type,
            tmdb_id,
            imdb_id,
            imdb_rating,
            imdb_votes,
            rt_score,
            omdb_status,
            omdb_last_checked,
            release_date,
            CASE
              WHEN omdb_status IS NULL
                THEN 0  -- never checked

              WHEN omdb_status = 'error'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '1 day')
                THEN 1  -- transient failure, retry quickly

              WHEN omdb_status = 'ok'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '7 days')
                THEN 2  -- refresh existing scores

              WHEN omdb_status = 'not_found'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '14 days')
                THEN 3  -- worth retrying after 2 weeks

              ELSE 99   -- skip
            END AS priority
        FROM media_ratings
        WHERE imdb_id IS NOT NULL
          AND media_type = 'movie'
          AND release_date >= now() - interval '{recent_months} months'
          {vote_filter}
          AND (
               omdb_status IS NULL
            OR (omdb_status = 'error'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '1 day'))
            OR (omdb_status = 'ok'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '7 days'))
            OR (omdb_status = 'not_found'
                AND (omdb_last_checked IS NULL
                     OR omdb_last_checked < now() - interval '14 days'))
          )
        ORDER BY
          priority ASC,
          release_date DESC,
          imdb_votes DESC NULLS LAST
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()

    return rows


def select_weekly_omdb_candidates(
    engine: Engine,
    limit: int = 1000,
    stale_months: int = 6,
    min_votes: int | None = None,
) -> Sequence[Mapping]:
    """
    WEEKLY selector: sweep broader catalog with budget-aware prioritization.

    Priority tiers (lower = higher priority):
      0) Never checked (omdb_status IS NULL) — highest value, no data at all
      1) Previously errored (omdb_status = 'error') — transient failure, worth retrying
      2) Has RT score but stale (omdb_last_checked > stale_months) — keep data fresh
      3) not_found but >12 months since last check — low-value retry, OMDb may have added data
      99) Everything else — skip

    Guards:
      - imdb_id IS NOT NULL
      - media_type = 'movie' (OMDb has very limited TV RT coverage)
      - optional imdb_votes >= min_votes
    """
    vote_filter = ""
    params: dict = {"limit": limit}

    if min_votes is not None:
        vote_filter = "AND (imdb_votes IS NULL OR imdb_votes >= :min_votes)"
        params["min_votes"] = min_votes

    sql = text(
        f"""
        SELECT
            media_type,
            tmdb_id,
            imdb_id,
            imdb_rating,
            imdb_votes,
            rt_score,
            omdb_status,
            omdb_last_checked,
            release_date,
            CASE
              WHEN omdb_status IS NULL
                THEN 0  -- never checked

              WHEN omdb_status = 'error'
                THEN 1  -- transient failure, retry

              WHEN rt_score IS NOT NULL
                AND omdb_last_checked < now() - interval '{stale_months} months'
                THEN 2  -- stale RT score, refresh

              WHEN omdb_status = 'not_found'
                AND omdb_last_checked < now() - interval '12 months'
                THEN 3  -- old not_found, worth retrying

              ELSE 99   -- skip
            END AS priority
        FROM media_ratings
        WHERE imdb_id IS NOT NULL
          AND media_type = 'movie'
          {vote_filter}
          AND (
               omdb_status IS NULL
            OR omdb_status = 'error'
            OR (rt_score IS NOT NULL
                AND omdb_last_checked < now() - interval '{stale_months} months')
            OR (omdb_status = 'not_found'
                AND omdb_last_checked < now() - interval '12 months')
          )
        ORDER BY
          priority ASC,
          imdb_votes DESC NULLS LAST,
          release_date DESC
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()

    return rows


def enrich_omdb_rows(
    engine: Engine,
    rows: Sequence[Mapping],
    sleep_between: float = 0.3,
    flush_every: int = 50,
) -> None:
    """
    Shared micro-batch OMDb enrichment loop.

    Calls fetch_from_omdb per row and flushes updates to media_ratings
    every `flush_every` calls for crash resilience.
    """
    if not rows:
        logger.info("No candidates require OMDb enrichment.")
        return

    logger.info("Enriching %d candidates via OMDb...", len(rows))

    update_sql = text(
        """
        UPDATE media_ratings
        SET rt_score         = :rt_score,
            omdb_last_checked = now(),
            omdb_status       = :omdb_status,
            metascore         = :metascore,
            awards_summary    = :awards_summary,
            updated_at        = now()
        WHERE tmdb_id   = :tmdb_id
          AND media_type = :media_type
          AND (
               rt_score       IS DISTINCT FROM :rt_score
            OR omdb_status    IS DISTINCT FROM :omdb_status
            OR metascore      IS DISTINCT FROM :metascore
            OR awards_summary IS DISTINCT FROM :awards_summary
          )
        """
    )

    batch_updates: list[dict] = []
    total_processed = 0
    total_flushed = 0
    total_batches = (len(rows) + flush_every - 1) // flush_every

    for idx, row in enumerate(rows, start=1):
        rt_score, metascore, awards, status = fetch_from_omdb(row["imdb_id"])

        batch_updates.append(
            {
                "media_type": row["media_type"],
                "tmdb_id": row["tmdb_id"],
                "rt_score": rt_score,
                "omdb_status": status,
                "metascore": metascore,
                "awards_summary": awards,
            }
        )

        total_processed += 1
        time.sleep(sleep_between)

        # Flush micro-batch to DB
        if len(batch_updates) >= flush_every or idx == len(rows):
            batch_num = (idx + flush_every - 1) // flush_every
            with engine.begin() as conn:
                conn.execute(update_sql, batch_updates)

            total_flushed += len(batch_updates)
            logger.info(
                "Flushed batch %d/%d: %d processed (total: %d/%d)",
                batch_num,
                total_batches,
                len(batch_updates),
                total_flushed,
                len(rows),
            )
            batch_updates = []

    logger.info(
        "OMDb enrichment complete: %d candidates processed.", total_processed
    )


# == Step 4: Sync ratings from media_ratings into Qdrant payload ==
def select_ratings_for_qdrant_sync(
    engine: Engine,
    limit: int = 1000,
) -> Sequence[Mapping]:
    """
    Criteria:
    - Never synced (qdrant_synced_at IS NULL)
    - OR updated since last sync (updated_at > qdrant_synced_at)
    """
    sql = text(
        """
        SELECT media_type,
               tmdb_id,
               imdb_rating,
               imdb_votes,
               rt_score,
               metascore,
               awards_summary,
               updated_at
        FROM media_ratings
        WHERE (qdrant_synced_at IS NULL OR updated_at > qdrant_synced_at)
          AND media_type = 'movie'
        ORDER BY updated_at ASC
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).mappings().all()

    return rows


def sync_ratings_to_qdrant(engine: Engine, batch_size: int = 1000) -> None:
    """
    Incrementally sync imdb_rating, imdb_votes, rt_score, metascore, awards_summary
    into Qdrant payload.

    Uses qdrant_synced_at as a watermark so that each row is only sent when it's
    new or changed.

    - Still calls Qdrant per point (API requires one payload dict per call).
    - Batches the Postgres UPDATE into a single executemany per batch.
    """
    client = connect_qdrant(QDRANT_API_KEY, QDRANT_ENDPOINT)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    update_sql = text(
        """
        UPDATE media_ratings
        SET qdrant_synced_at = :synced_at
        WHERE tmdb_id = :tmdb_id
          AND media_type = :media_type
        """
    )

    batch_count = 0

    while True:
        batch_count += 1
        rows = select_ratings_for_qdrant_sync(engine, limit=batch_size)
        if not rows:
            logger.info("No ratings to sync to Qdrant.")
            break

        logger.info("Starting Qdrant sync batch #%d", batch_count)
        logger.info("Syncing %d ratings rows to Qdrant...", len(rows))

        updates: list[dict] = []

        for row in rows:
            tmdb_id = row["tmdb_id"]
            media_type = row["media_type"]

            if media_type == "movie":
                collection_name = QDRANT_MOVIE_COLLECTION_NAME
            elif media_type == "tv":
                collection_name = QDRANT_TV_COLLECTION_NAME
            else:
                logger.warning(
                    "Skipping tmdb_id=%s with invalid media_type=%s",
                    tmdb_id,
                    media_type,
                )
                continue

            payload = {
                "imdb_rating": row["imdb_rating"],
                "imdb_votes": row["imdb_votes"],
                "rt_score": row["rt_score"],
                "metascore": row["metascore"],
                "awards_summary": row["awards_summary"],
            }

            # Qdrant expects a single dict as `payload`, not a list
            try:
                client.set_payload(
                    collection_name=collection_name,
                    payload=payload,
                    points=[tmdb_id],
                )
            except UnexpectedResponse as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code == 404 or "Not found" in str(exc):
                    logger.warning(
                        "Qdrant point not found for tmdb_id=%s (media_type=%s). Skipping.",
                        tmdb_id,
                        media_type,
                    )
                    continue
                raise

            updates.append(
                {
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "synced_at": row["updated_at"],
                }
            )

        # Batch DB updates for all successfully synced rows
        if updates:
            with engine.begin() as conn:
                conn.execute(update_sql, updates)

        logger.info(
            "Finished Qdrant sync batch #%d; marked %d rows as synced.",
            batch_count,
            len(updates),
        )

    logger.info("Ratings fully synced to Qdrant.")
