from fastapi import Request
from typing import cast
from app.infrastructure.cache.ticket_store import TicketStore

def get_ticket_store(request: Request) -> TicketStore:
    store = getattr(request.app.state, "ticket_store", None)
    if store is None:
        raise RuntimeError("ticket_store not initialized")
    return cast(TicketStore, store)
