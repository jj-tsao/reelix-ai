"""Span-link helpers for joining the two phases of a recommendation request.

The slate call and the later "why" call run as separate root traces (the gap
between them can be minutes), so the originating span context is stashed in
the Redis ticket and rebuilt into a span Link when the ticket is redeemed.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Link, SpanContext, TraceFlags


def otel_link_meta() -> dict | None:
    """Capture the current span context for stashing in a why-ticket, so the
    later explanation trace can link back to this one.
    Returns None when no valid span is recording."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return {
        "otel": {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
            "trace_flags": int(ctx.trace_flags),
        }
    }


def link_from_ticket_meta(meta: dict | None) -> Link | None:
    """Rebuild a span Link to the originating trace from ticket meta."""
    otel = (meta or {}).get("otel")
    if not isinstance(otel, dict):
        return None
    try:
        parent_ctx = SpanContext(
            trace_id=int(otel["trace_id"], 16),
            span_id=int(otel["span_id"], 16),
            is_remote=True,
            trace_flags=TraceFlags(int(otel.get("trace_flags", TraceFlags.SAMPLED))),
        )
    except (KeyError, ValueError, TypeError):
        return None
    return Link(parent_ctx) if parent_ctx.is_valid else None