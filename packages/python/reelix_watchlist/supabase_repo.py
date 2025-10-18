from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Tuple

from anyio import to_thread
from postgrest.exceptions import APIError as PostgrestAPIError

from .errors import NotFound
from .schemas import (
    ExistsOut,
    WatchlistCreate,
    WatchlistItem,
    WatchlistRemoveById,
    WatchlistUpdate,
    WatchStatus,
)

TABLE = "user_watchlist"
RPC_SOFT_DELETE = "soft_delete_watchlist_row"  # make sure this function exists in DB
DENORM_FIELDS = {
    "title",
    "poster_url",
    "backdrop_url",
    "release_year",
    "genres",
    "source",
}


def _row_to_item(row: dict) -> WatchlistItem:
    return WatchlistItem(**row)


class SupabaseWatchlistRepo:
    def __init__(self, client):
        self.client = client

    # ---------- Async facade (runs sync work in threadpool) ----------

    async def create_or_revive(self, dto: WatchlistCreate) -> WatchlistItem:
        return await to_thread.run_sync(self._create_revive_sync, dto)

    async def update(self, dto: WatchlistUpdate) -> WatchlistItem:
        return await to_thread.run_sync(self._update_sync, dto)

    async def remove_by_id(self, dto: WatchlistRemoveById) -> WatchlistItem:
        return await to_thread.run_sync(self._remove_by_id_sync, dto)

    async def list(
        self,
        user_id: str,
        *,
        status: WatchStatus | None,
        q: str | None,
        year_min: int | None,
        year_max: int | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> Tuple[Sequence[WatchlistItem], int]:
        return await to_thread.run_sync(
            self._list_sync,
            user_id,
            status,
            q,
            year_min,
            year_max,
            sort,
            page,
            page_size,
        )

    async def exists(self, user_id: str, media_id: int, media_type: str) -> ExistsOut:
        return await to_thread.run_sync(
            self._exists_sync, user_id, media_id, media_type
        )

    async def get(self, user_id: str, id: str) -> WatchlistItem:
        return await to_thread.run_sync(self._get_sync, user_id, id)

    # ---------- Private sync implementations ----------

    def _create_revive_sync(self, dto: WatchlistCreate) -> WatchlistItem:
        payload = dto.model_dump(exclude_none=True)

        # 0) Active exists? return as-is
        existing = (
            self.client.table(TABLE)
            .select("*")
            .eq("user_id", dto.user_id)
            .eq("media_id", dto.media_id)
            .eq("media_type", dto.media_type)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if existing.data:
            return _row_to_item(existing.data[0])

        # 1) Revive a soft-deleted row
        revive_updates = {"deleted_at": None, "deleted_reason": None}
        # optional: backfill denorms only if currently null
        for k in DENORM_FIELDS:
            if k in payload:
                revive_updates[k] = payload[k]

        revived = (
            self.client.table(TABLE)
            .update(revive_updates, returning="representation")
            .eq("user_id", dto.user_id)
            .eq("media_id", dto.media_id)
            .eq("media_type", dto.media_type)
            .not_.is_("deleted_at", None)
            .execute()
        )
        if revived.data:
            return _row_to_item(revived.data[0])

        # 2) Fresh insert
        try:
            res = (
                self.client.table(TABLE)
                .insert(payload, returning="representation")
                .execute()
            )
            return _row_to_item(res.data[0])
        except PostgrestAPIError as e:
            # Race: someone inserted after this check → read active and return
            if getattr(e, "code", None) == "23505":
                final = (
                    self.client.table(TABLE)
                    .select("*")
                    .eq("user_id", dto.user_id)
                    .eq("media_id", dto.media_id)
                    .eq("media_type", dto.media_type)
                    .is_("deleted_at", None)
                    .limit(1)
                    .execute()
                )
                if final.data:
                    return _row_to_item(final.data[0])
            raise

    def _update_sync(self, dto: WatchlistUpdate) -> WatchlistItem:
        # 1) Ensure the row exists AND is not soft-deleted
        exists = (
            self.client.table(TABLE)
            .select("id")  # small projection
            .eq("id", dto.id)
            .eq("user_id", dto.user_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not exists.data:
            raise NotFound("watchlist item not found")

        # 2) Build allowed updates (no deleted_at changes here)
        updates: dict[str, object] = {}
        if dto.status is not None:
            updates["status"] = (
                dto.status.value if hasattr(dto.status, "value") else dto.status
            )
        if dto.rating is not None:
            updates["rating"] = dto.rating
        if dto.notes is not None:
            updates["notes"] = dto.notes

        # No-op: return current row
        if not updates:
            current = (
                self.client.table(TABLE)
                .select("*")
                .eq("id", dto.id)
                .eq("user_id", dto.user_id)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if not current.data:
                raise NotFound("watchlist item not found")
            return _row_to_item(current.data[0])

        # 3) Apply update and return the updated row
        res = (
            self.client.table(TABLE)
            .update(updates, returning="representation")
            .eq("id", dto.id)
            .eq("user_id", dto.user_id)
            .is_("deleted_at", None)
            .execute()
        )
        if not res.data:
            # In case the row was soft-deleted between the check and update
            raise NotFound("watchlist item not found")

        return _row_to_item(res.data[0])

    def _remove_by_id_sync(self, dto: WatchlistRemoveById) -> WatchlistItem:
        res = (
            self.client.table(TABLE)
            .update(
                {
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                    "deleted_reason": "user_removed",
                },
                returning="representation",
            )
            .eq("id", dto.id)
            .eq("user_id", dto.user_id)
            .is_("deleted_at", None)  # only active rows
            .execute()
        )
        data = res.data or []
        if not data:
            raise NotFound("watchlist item not found")
        return _row_to_item(data[0])

    def _list_sync(
        self,
        user_id: str,
        status: WatchStatus | None,
        q: str | None,
        year_min: int | None,
        year_max: int | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> Tuple[Sequence[WatchlistItem], int]:
        qb = (
            self.client.table(TABLE)
            .select("*", count="exact")
            .eq("user_id", user_id)
            .is_("deleted_at", None)
        )
        if status:
            status_str = status.value if isinstance(status, WatchStatus) else status
            qb = qb.eq("status", status_str)
        if q:
            qb = qb.ilike("title", f"%{q}%")
        if year_min is not None:
            qb = qb.gte("release_year", year_min)
        if year_max is not None:
            qb = qb.lte("release_year", year_max)

        sort_map = {
            "added_desc":  ("created_at", True),
            "added_asc":   ("created_at", False),
            "year_desc":   ("release_year", True),
            "year_asc":    ("release_year", False),
            "rating_desc": ("rating", True),
            "rating_asc":  ("rating", False),
        }

        col, desc = sort_map.get(sort, ("created_at", True))

        if col == "rating":
            # Prefer explicit NULLS LAST for rating sorts
            try:
                # newer supabase-py exposes nulls_last
                qb = qb.order("rating", desc=desc, nullslast=True)
            except TypeError:
                # fallback: older clients only expose nulls_first
                if desc:
                    # DESC defaults to NULLS FIRST → force last
                    qb = qb.order("rating", desc=True, nullsfirst=False)
                else:
                    # ASC already defaults to NULLS LAST; leave as-is
                    qb = qb.order("rating", desc=False)
        else:
            qb = qb.order(col, desc=desc)

        start = (page - 1) * page_size
        end = start + page_size - 1
        res = qb.range(start, end).execute()

        items = [_row_to_item(r) for r in (res.data or [])]
        total = res.count or 0
        return items, total

    def _exists_sync(self, user_id: str, media_id: int, media_type: str) -> ExistsOut:
        res = (
            self.client.table(TABLE)
            .select("id,status,rating")
            .eq("user_id", user_id)
            .eq("media_id", media_id)
            .eq("media_type", media_type)
            .is_("deleted_at", None)  # active rows only
            .limit(1)
            .execute()
        )

        rows = res.data or []
        if not rows:
            return ExistsOut(exists=False)

        row = rows[0]
        status = self._to_watch_status(row.get("status"))

        return ExistsOut(
            exists=True,
            id=row.get("id"),
            status=status,
            rating=row.get("rating"),
        )

    def _to_watch_status(self, value: str | None = None) -> WatchStatus:
        try:
            return WatchStatus(value) if value is not None else WatchStatus.WANT
        except ValueError:
            # Unknown status in DB; be defensive but log if you want
            return WatchStatus.WANT

    def _get_sync(self, user_id: str, id: str) -> WatchlistItem:
        res = (
            self.client.table(TABLE)
            .select("*")
            .eq("id", id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            raise NotFound("watchlist item not found")
        return _row_to_item(res.data[0])
