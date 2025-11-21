from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, Dict, List

import redis.asyncio as redis  # type: ignore[import]

from reelix_core.types import MediaType


@dataclass
class CachedWhy:
    """
    Cached explanation for a (user, media_type, media_id) triple.
    """

    why_md: str
    imdb_rating: float | None = None
    rt_rating: float | None = None
    created_at: float = 0.0
    taste_version: str | None = None


class WhyCache(Protocol):
    async def get_many(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_ids: List[int],
    ) -> Dict[int, CachedWhy]: ...

    async def set_many(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        values: Dict[int, CachedWhy],
        ttl_sec: int | None = None,
    ) -> None: ...

    async def get_one(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_id: int,
    ) -> CachedWhy | None: ...

    async def set_one(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_id: int,
        value: CachedWhy,
        ttl_sec: int | None = None,
    ) -> None: ...


class RedisWhyCache(WhyCache):
    """
    Redis-backed why cache. One key per (user, media_type, media_id).
    Key:   {namespace}{user_id}:{media_type}:{media_id}
    Value: JSON string of CachedWhy fields.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        namespace: str = "disc:why:",
        default_ttl_sec: int = 7 * 24 * 3600,
        client_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not redis_url:
            raise ValueError("redis_url must be provided for RedisWhyCache")
        self._ns = namespace
        self._default_ttl = int(default_ttl_sec)
        client_kwargs = client_kwargs or {}
        self._r = redis.from_url(
            redis_url,
            decode_responses=True,  # store JSON as plain strings
            **client_kwargs,
        )

    def _key(self, user_id: str, media_type: MediaType, media_id: int) -> str:
        return f"{self._ns}{user_id}:{media_type.value}:{media_id}"

    def _serialize(self, value: CachedWhy) -> str:
        payload = {
            "why_md": value.why_md,
            "imdb_rating": value.imdb_rating,
            "rt_rating": value.rt_rating,
            "created_at": value.created_at,
            "taste_version": value.taste_version,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _deserialize(self, s: str | None) -> CachedWhy | None:
        if not s:
            return None
        try:
            data = json.loads(s)
        except Exception:
            return None
        why_md = data.get("why_md")
        if not isinstance(why_md, str):
            return None
        return CachedWhy(
            why_md=why_md,
            imdb_rating=data.get("imdb_rating"),
            rt_rating=data.get("rt_rating"),
            created_at=float(data.get("created_at") or 0.0),
            taste_version=data.get("taste_version"),
        )

    async def get_many(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_ids: List[int],
    ) -> Dict[int, CachedWhy]:
        if not media_ids:
            return {}
        keys = [self._key(user_id, media_type, mid) for mid in media_ids]
        pipe = self._r.pipeline()
        for k in keys:
            pipe.get(k)
        results = await pipe.execute()
        out: Dict[int, CachedWhy] = {}
        for mid, raw in zip(media_ids, results):
            value = self._deserialize(raw)
            if value is not None:
                out[mid] = value
        return out

    async def set_many(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        values: Dict[int, CachedWhy],
        ttl_sec: int | None = None,
    ) -> None:
        if not values:
            return
        ttl = int(ttl_sec or self._default_ttl)
        pipe = self._r.pipeline()
        for mid, value in values.items():
            k = self._key(user_id, media_type, mid)
            v = self._serialize(value)
            pipe.set(k, v, ex=ttl)
        await pipe.execute()

    async def get_one(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_id: int,
    ) -> CachedWhy | None:
        res = await self.get_many(
            user_id=user_id,
            media_type=media_type,
            media_ids=[media_id],
        )
        return res.get(media_id)

    async def set_one(
        self,
        *,
        user_id: str,
        media_type: MediaType,
        media_id: int,
        value: CachedWhy,
        ttl_sec: int | None = None,
    ) -> None:
        await self.set_many(
            user_id=user_id,
            media_type=media_type,
            values={media_id: value},
            ttl_sec=ttl_sec,
        )

    async def aclose(self) -> None:
        try:
            await self._r.aclose()
        except Exception:
            pass
