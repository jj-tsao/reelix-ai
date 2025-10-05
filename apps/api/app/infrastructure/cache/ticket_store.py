# ticket_store.py
from __future__ import annotations

import gzip
import json
import time
from typing import Optional

import redis.asyncio as redis


class Ticket:
    __slots__ = ("user_id", "prompts", "created_at")

    def __init__(self, user_id: str, prompts: dict, created_at: float | None = None):
        self.user_id = user_id
        self.prompts = prompts
        self.created_at = created_at or time.time()


class TicketStore:
    async def put(self, key: str, ticket: Ticket, ttl_sec: int): ...
    async def get(self, key: str) -> Optional[Ticket]: ...
    async def delete(self, key: str): ...


class MemoryTicketStore(TicketStore):
    def __init__(self):
        self._m = {}

    async def put(self, k, t, ttl):
        self._m[k] = (t, time.time() + ttl)

    async def get(self, k):
        v = self._m.get(k)
        if not v:
            return None
        t, exp = v
        if time.time() > exp:
            self._m.pop(k, None)
            return None
        return t

    async def delete(self, k):
        self._m.pop(k, None)


class RedisTicketStore(TicketStore):
    def __init__(self, url: str, namespace: str = "disc:ticket:"):
        self.r = redis.from_url(url, decode_responses=False)  # store bytes
        self.ns = namespace

    def _k(self, k):
        return f"{self.ns}{k}"

    async def put(self, k: str, t: Ticket, ttl_sec: int):
        payload = {
            "user_id": t.user_id,
            "prompts": t.prompts,
            "created_at": t.created_at,
        }
        b = gzip.compress(json.dumps(payload).encode("utf-8"))
        await self.r.set(self._k(k), b, ex=ttl_sec)

    async def get(self, k: str) -> Optional[Ticket]:
        b = await self.r.get(self._k(k))
        if not b:
            return None
        data = json.loads(gzip.decompress(b).decode("utf-8"))
        return Ticket(
            user_id=data["user_id"],
            prompts=data["prompts"],
            created_at=data["created_at"],
        )

    async def delete(self, k: str):
        await self.r.delete(self._k(k))
