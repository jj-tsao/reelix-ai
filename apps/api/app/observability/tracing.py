from __future__ import annotations

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from reelix_runtime.telemetry.tracing import init_tracing_core


def init_tracing(app: FastAPI) -> None:
    """Initialize tracing for the API process.

    Delegates provider/exporter setup and HTTPX/Redis instrumentation to the
    shared ``init_tracing_core``, then adds FastAPI auto-instrumentation so
    each request gets a root server span.
    """
    init_tracing_core(default_service_name="reelix-api")
    FastAPIInstrumentor.instrument_app(app)