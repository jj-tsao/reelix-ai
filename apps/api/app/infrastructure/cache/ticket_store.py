# ticket_store.py
from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

try:
    # Optional dependency: only needed if you use the Redis backend.
    import redis.asyncio as redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None  # Lazy import guard for environments without redis

JsonObj = dict[str, Any]
MutateFn = Callable[[Any], None]


# ---------------------------
# Models
# ---------------------------

@dataclass
class Ticket:
    """
    Session 'ticket' that lets GET /why stream what POST /for-you prepared.

    - user_id: used for auth checks on /why
    - prompts: either fully-rendered LLM calls or a minimal spec to rebuild
    - created_at: epoch seconds (float); used for absolute TTL capping
    - meta: optional small traceability blob (recipe, prompt_hash, items_brief, etc.)
    """
    user_id: str
    prompts: Any
    created_at: float | None = None
    meta: Optional[JsonObj] = None

    def ensure_created(self) -> None:
        if self.created_at is None:
            self.created_at = time.time()


# ---------------------------
# Interface
# ---------------------------

class TicketStore(Protocol):
    """Abstract store for tickets"""

    async def put(self, key: str, ticket: Ticket, ttl_sec: int) -> None: ...
    async def get(self, key: str) -> Optional[Ticket]: ...
    async def delete(self, key: str) -> None: ...
    async def touch(self, key: str, ttl_sec: int) -> bool: ...
    async def update(self, key: str, ttl_sec: int, mutate: MutateFn) -> bool: ...
    async def aclose(self) -> None: ...


# ---------------------------
# Memory implementation
# ---------------------------

class MemoryTicketStore(TicketStore):
    """
    Simple process-local store for single-worker deployments.
    Not shared across workers/pods. Use RedisTicketStore when you scale.
    """
    def __init__(self) -> None:
        # key -> (ticket, expires_at_epoch)
        self._m: dict[str, tuple[Ticket, float]] = {}

    async def put(self, key: str, ticket: Ticket, ttl_sec: int) -> None:
        ticket.ensure_created()
        self._m[key] = (ticket, time.time() + float(ttl_sec))

    async def get(self, key: str) -> Optional[Ticket]:
        t = self._m.get(key)
        if not t:
            return None
        ticket, exp = t
        now = time.time()
        if now > exp:
            self._m.pop(key, None)
            return None
        # Absolute TTL cap handled by caller or meta (not needed in memory unless desired)
        return ticket

    async def delete(self, key: str) -> None:
        self._m.pop(key, None)

    async def touch(self, key: str, ttl_sec: int) -> bool:
        t = self._m.get(key)
        if not t:
            return False
        ticket, _ = t
        self._m[key] = (ticket, time.time() + float(ttl_sec))
        return True

    async def update(self, key: str, ttl_sec: int, mutate: MutateFn) -> bool:
        t = self._m.get(key)
        if not t:
            return False
        ticket, _ = t
        try:
            mutate(ticket)  # mutate in place (e.g., append next batch)
        except Exception:
            # Prevent corrupting the store on mutation failure
            return False
        self._m[key] = (ticket, time.time() + float(ttl_sec))
        return True

    async def aclose(self) -> None:
        # Nothing to close for memory store
        return


# ---------------------------
# Redis implementation
# ---------------------------

class RedisTicketStore(TicketStore):
    """
    Redis-backed store with gzip'd JSON payloads.
    Supports sliding TTL via touch(), plus an absolute TTL cap to avoid zombies.
    """

    def __init__(
        self,
        url: str,
        *,
        namespace: str = "disc:ticket:",
        absolute_ttl_sec: int = 60 * 60,  # 1 hour cap
        compression_level: int = 5,
        client_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        if redis is None:  # pragma: no cover
            raise RuntimeError("redis-py not installed; install `redis` to use RedisTicketStore")
        self._ns = namespace
        self._abs_ttl = int(absolute_ttl_sec)
        self._level = int(compression_level)
        client_kwargs = client_kwargs or {}
        # Decode_responses=False => bytes in/out (we gzip the JSON)
        self._r = redis.from_url(url, decode_responses=False, **client_kwargs)

    def _k(self, key: str) -> str:
        return f"{self._ns}{key}"

    # ---- serialization helpers ----

    def _serialize(self, ticket: Ticket) -> bytes:
        ticket.ensure_created()
        payload: JsonObj = {
            "user_id": ticket.user_id,
            "prompts": ticket.prompts,
            "created_at": ticket.created_at,
        }
        if ticket.meta is not None:
            payload["meta"] = ticket.meta
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return gzip.compress(raw, compresslevel=self._level)

    def _deserialize(self, blob: bytes) -> Optional[Ticket]:
        try:
            raw = gzip.decompress(blob)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        created_at = float(data.get("created_at", 0.0) or 0.0)
        if self._abs_ttl and (time.time() - created_at) > self._abs_ttl:
            # Let caller delete; just signal expired by returning None
            return None
        return Ticket(
            user_id=str(data.get("user_id", "")),
            prompts=data.get("prompts"),
            created_at=created_at or time.time(),
            meta=data.get("meta") if isinstance(data.get("meta"), dict) else None,
        )

    # ---- API ----

    async def put(self, key: str, ticket: Ticket, ttl_sec: int) -> None:
        b = self._serialize(ticket)
        await self._r.set(self._k(key), b, ex=int(ttl_sec))

    async def get(self, key: str) -> Optional[Ticket]:
        b = await self._r.get(self._k(key))
        if not b:
            return None
        ticket = self._deserialize(b)
        if ticket is None:
            # Absolute TTL exceeded or decode error: clean up
            await self.delete(key)
            return None
        return ticket

    async def delete(self, key: str) -> None:
        await self._r.delete(self._k(key))

    async def touch(self, key: str, ttl_sec: int) -> bool:
        # Refresh idle TTL (sliding)
        res = await self._r.expire(self._k(key), int(ttl_sec))
        return bool(res)

    async def update(self, key: str, ttl_sec: int, mutate: MutateFn) -> bool:
        """
        Read-modify-write with TTL refresh. Not atomic across processes.
        If you need atomicity, wrap with a short-lived Lua script or a
        simple optimistic lock using GET/SETNX of a lock key.
        """
        k = self._k(key)
        blob = await self._r.get(k)
        if not blob:
            return False

        # Decode / mutate / encode
        try:
            raw = gzip.decompress(blob)
            data = json.loads(raw.decode("utf-8"))
            mutate(data)  # e.g., data["prompts"]["calls"].extend(next_calls)
            new_blob = gzip.compress(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                compresslevel=self._level,
            )
        except Exception:
            return False

        # Write back and refresh TTL
        await self._r.set(k, new_blob, ex=int(ttl_sec))
        return True

    async def aclose(self) -> None:
        try:
            await self._r.aclose()
        except Exception:
            pass


# ---------------------------
# Convenience factory
# ---------------------------

def make_ticket_store(
    use_redis: bool,
    *,
    redis_url: str = "",
    namespace: str = "disc:ticket:",
    absolute_ttl_sec: int = 3600,
    compression_level: int = 5,
    client_kwargs: Optional[dict[str, Any]] = None,
) -> TicketStore:
    """
    Create a TicketStore based on config flags.
    """
    if use_redis:
        if not redis_url:
            raise ValueError("redis_url must be provided when use_redis=True")
        return RedisTicketStore(
            redis_url,
            namespace=namespace,
            absolute_ttl_sec=absolute_ttl_sec,
            compression_level=compression_level,
            client_kwargs=client_kwargs,
        )
    return MemoryTicketStore()
