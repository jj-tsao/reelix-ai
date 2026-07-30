from fastapi import Request
from typing import cast
from reelix_runtime.cache.ticket_store import TicketStore
from reelix_runtime.cache.state_store import StateStore
from reelix_runtime.cache.why_cache import WhyCache


def get_ticket_store(request: Request) -> TicketStore:
    store = getattr(request.app.state, "ticket_store", None)
    if store is None:
        raise RuntimeError("ticket_store not initialized")
    return cast(TicketStore, store)


def get_state_store(request: Request) -> StateStore:
    store = getattr(request.app.state, "state_store", None)
    if store is None:
        raise RuntimeError("state_store not initialized")
    return cast(StateStore, store)

def get_why_cache(request: Request) -> WhyCache:
    store = getattr(request.app.state, "why_cache", None)
    if store is None:
        raise RuntimeError("why_cache not initialized")
    return cast(WhyCache, store)
