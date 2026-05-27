from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.semconv._incubating.attributes.deployment_attributes import (
    DEPLOYMENT_ENVIRONMENT_NAME,
)
from opentelemetry.semconv.attributes.service_attributes import (
    SERVICE_NAME,
    SERVICE_VERSION,
)

_INITIALIZED = False


def init_tracing(app: FastAPI) -> None:
    """Initialize the global TracerProvider, install auto-instrumentation

    Reads standard OTEL_* env vars:
      OTEL_SERVICE_NAME            (default: reelix-api)
      OTEL_EXPORTER_OTLP_ENDPOINT  Grafana Cloud OTLP gateway
      OTEL_EXPORTER_OTLP_HEADERS   e.g. "Authorization=Basic <token>"
      OTEL_TRACES_EXPORTER         "otlp", "console", or "none". Default is
                                   "otlp" when an OTLP endpoint is configured,
                                   else "none" — so a bare dev server doesn't
                                   spam connection errors to localhost:4318.
      OTEL_TRACES_SAMPLER, OTEL_TRACES_SAMPLER_ARG
                                   default sampler is parentbased_always_on
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "reelix-api"),
            SERVICE_VERSION: os.getenv("REELIX_VERSION", "0.1.0"),
            DEPLOYMENT_ENVIRONMENT_NAME: os.getenv("REELIX_ENV", "development"),
        }
    )

    provider = TracerProvider(resource=resource)

    # Default to OTLP only when an endpoint is configured; otherwise stay silent
    # so a local dev server without a collector doesn't retry-spam localhost:4318.
    has_otlp_endpoint = bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )
    default_exporter = "otlp" if has_otlp_endpoint else "none"
    exporter = os.getenv("OTEL_TRACES_EXPORTER", default_exporter).lower()
    if exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "none":
        pass
    else:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    _INITIALIZED = True