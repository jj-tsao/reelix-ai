from __future__ import annotations
import os
import time
import hmac
import hashlib
from typing import Any, Iterable, Literal
import httpx
from pydantic import BaseModel

Endpoint = Literal["discovery", "recommendations"]


# ---------- Public models (optional typing nicety) ----------
class DeviceInfo(BaseModel):
    device_type: str | None = None
    platform: str | None = None
    user_agent: str | None = None


# ---------- Core logger ----------
class TelemetryLogger:
    """
    One shared logger for discovery & recommendations.

    - rec_queries: one row per request
    - rec_results: one row per ranked candidate
    - rec_stream_events: optional SSE lifecycle (started | why_delta | done | error)
    - rec_recommendations_ext: extension for /recommendations (e.g., query_text)

    Usage (examples at bottom):
      logger = RecLogger.from_env(sample=1.0)
      await logger.log_query_started(endpoint="discover", ...)
      await logger.log_candidates(endpoint="discover", query_id=..., candidates=[...])
      agg = logger.start_stream(endpoint="discover", query_id=..., batch_id=1)
      await agg.flush_started(); agg.add_delta(media_id, len_bytes); await agg.flush_delta(); await agg.flush_done()
    """

    def __init__(
        self,
        supabase_url: str,
        api_key: str,
        client,
        *,
        sample: float = 1.0,
        timeout_s: float = 5.0,
    ):
        self.supabase_url = supabase_url.rstrip("/")
        self.api_key = api_key
        self.client = client
        self.sample = float(max(0.0, min(1.0, sample)))
        self.timeout_s = timeout_s

    def _enabled(self) -> bool:
        return bool(self.supabase_url and self.api_key and self.sample > 0)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

    async def _post(
        self, client: httpx.AsyncClient, path: str, payload: list[dict[str, Any]]
    ) -> None:
        if not self._enabled() or not payload:
            return
        try:
            r = await client.post(
                f"{self.supabase_url}/rest/v1/{path}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            if r.status_code not in (200, 201, 204):
                print(
                    f"⚠️ rec_logger POST {path} failed {r.status_code}: {r.text[:300]}"
                )
        except Exception as e:
            print(f"❌ rec_logger POST {path} error: {e}")

    @staticmethod
    def hmac_hash(value: str, secret: str) -> str:
        return hmac.new(
            secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    # ---------- Public APIs ----------
    async def log_query_intake(
        self,
        *,
        endpoint: Endpoint,
        query_id: str,
        user_id: str | None = None,
        session_id: str | None = None,
        media_type: str,
        pipeline_version: str | None,
        batch_size: int,
        device_info: DeviceInfo | None = None,
        request_meta: dict[str, Any] | None = None,
    ) -> None:
        """
        Insert into rec_queries (one row).
        """
        if not self._enabled():
            return
        meta = dict(request_meta or {})
        if device_info is not None:
            meta["device"] = device_info.model_dump()

        row = {
            "endpoint": endpoint,
            "query_id": query_id,
            "user_id": user_id,
            "session_id": session_id,
            "media_type": media_type,
            "pipeline_version": pipeline_version,
            "batch_size": int(batch_size),
            "request_meta": meta,
        }
        async with httpx.AsyncClient() as client:
            await self._post(client, "rec_queries", [row])

    async def log_candidates(
        self,
        *,
        endpoint: Endpoint,
        query_id: str,
        candidates: Iterable[dict[str, Any]],
    ) -> None:
        """
        Insert N rows into rec_results. Each candidate dict can include:
          media_id (str), rank (int), title (str), release_year (int), genres (list[str]),
          poster_url (str), score_final (float), score_parts (dict), source_meta (dict)
        """
        if not self._enabled():
            return
        rows = []
        for c in candidates:
            row = {"endpoint": endpoint, "query_id": query_id}
            row.update(c or {})
            rows.append(row)
        if not rows:
            return
        async with httpx.AsyncClient() as client:
            await self._post(client, "rec_results", rows)

    def start_stream(
        self, *, endpoint: Endpoint, query_id: str, batch_id: int | None
    ) -> "StreamAggregator":
        return StreamAggregator(
            logger=self, endpoint=endpoint, query_id=query_id, batch_id=batch_id
        )

    async def log_recommendations_ext(
        self,
        *,
        query_id: str,
        query_text: str,
        language: str | None = None,
        filters: dict | None = None,
        intent: dict | None = None,
        params: dict | None = None,
    ) -> None:
        """
        Insert one row into rec_recommendations_ext (for /recommendations/interactive).
        """
        if not self._enabled():
            return
        payload = [
            {
                "query_id": query_id,
                "query_text": query_text,
                "language": language,
                "filters": (filters or {}),
                "intent": (intent or {}),
                "params": (params or {}),
            }
        ]
        async with httpx.AsyncClient() as client:
            await self._post(client, "rec_recommendations_ext", payload)

    async def upsert_session(
        self,
        *,
        session_id: str,
        hashed_user_id: str | None,
        device: DeviceInfo | None = None,
    ) -> None:
        """
        Optional: maintain rec_client_sessions by session_id.
        """
        if not self._enabled():
            return
        row = {
            "session_id": session_id,
            "hashed_user_id": hashed_user_id,
            "last_seen": "now()",
            "request_count": 1,
        }
        if device is not None:
            data = device.model_dump()
            row["device_type"] = data.get("device_type")
            row["platform"] = data.get("platform")
            row["user_agent"] = data.get("user_agent")
        async with httpx.AsyncClient() as client:
            await self._post(client, "rec_client_sessions", [row])


# ---------- SSE stream aggregator ----------
class StreamAggregator:
    """
    Best-effort, non-blocking tracker for SSE phases:
      started -> multiple why_delta aggregates -> done | error
    """

    def __init__(
        self,
        logger: TelemetryLogger,
        *,
        endpoint: Endpoint,
        query_id: str,
        batch_id: int | None,
    ):
        self.logger = logger
        self.endpoint = endpoint
        self.query_id = query_id
        self.batch_id = batch_id
        self.media_stats: dict[
            str, dict[str, int]
        ] = {}  # media_id -> {chunk_count, bytes_total}
        self.t0 = time.time()

    def add_delta(self, media_id: str, chunk_bytes: int) -> None:
        st = self.media_stats.setdefault(media_id, {"chunk_count": 0, "bytes_total": 0})
        st["chunk_count"] += 1
        st["bytes_total"] += max(0, int(chunk_bytes))

    async def flush_started(self) -> None:
        await self._write(
            [
                {
                    "endpoint": self.endpoint,
                    "query_id": self.query_id,
                    "batch_id": self.batch_id,
                    "event": "started",
                }
            ]
        )

    async def flush_delta(self) -> None:
        if not self.media_stats:
            return
        rows = []
        for mid, st in self.media_stats.items():
            rows.append(
                {
                    "endpoint": self.endpoint,
                    "query_id": self.query_id,
                    "batch_id": self.batch_id,
                    "event": "why_delta",
                    "media_id": mid,
                    "chunk_count": st["chunk_count"],
                    "bytes_total": st["bytes_total"],
                }
            )
        self.media_stats.clear()
        await self._write(rows)

    async def flush_done(self, error_message: str | None = None) -> None:
        dur_ms = int((time.time() - self.t0) * 1000)
        row = {
            "endpoint": self.endpoint,
            "query_id": self.query_id,
            "batch_id": self.batch_id,
            "event": "error" if error_message else "done",
            "duration_ms": dur_ms,
            "error_message": error_message,
        }
        await self._write([row])

    async def _write(self, rows: list[dict[str, Any]]) -> None:
        if not self.logger._enabled() or not rows:
            return
        async with httpx.AsyncClient() as client:
            await self.logger._post(client, "rec_stream_events", rows)


# ---------- Convenience helpers ----------
def hash_user_id(user_id: str | None) -> str | None:
    if not user_id:
        return None
    secret = os.getenv("REC_HASH_SECRET") or os.getenv("SUPABASE_API_KEY") or "dev"
    return TelemetryLogger.hmac_hash(user_id, secret)
