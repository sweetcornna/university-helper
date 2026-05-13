"""OpenTelemetry tracing — env-flagged opt-in.

Enabled only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set. The OpenTelemetry
SDK and instrumentation packages are imported lazily so the project keeps
booting without them installed (CI doesn't pull them in by default).

To use locally:

    pip install opentelemetry-sdk opentelemetry-exporter-otlp \
        opentelemetry-instrumentation-fastapi \
        opentelemetry-instrumentation-psycopg2 \
        opentelemetry-instrumentation-requests
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    export OTEL_SERVICE_NAME=university-helper
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def configure_tracing(app: Any) -> None:
    """If OTLP endpoint is configured, wire FastAPI + libs to OTel.

    Safe to call regardless: returns silently when tracing isn't enabled
    or when the SDK isn't installed.
    """
    endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if not endpoint:
        return

    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-not-found]
        from opentelemetry.instrumentation.fastapi import (  # type: ignore[import-not-found]
            FastAPIInstrumentor,
        )
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT=%s but opentelemetry-* packages are not "
            "installed — tracing disabled. Install opentelemetry-sdk + the "
            "relevant instrumentors to enable.",
            endpoint,
        )
        return

    service_name = os.getenv("OTEL_SERVICE_NAME") or "university-helper"
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)

    # Best-effort optional instrumentors.
    for module, attr in [
        ("opentelemetry.instrumentation.psycopg2", "Psycopg2Instrumentor"),
        ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
        ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    ]:
        try:
            mod = __import__(module, fromlist=[attr])
            getattr(mod, attr)().instrument()
        except ImportError:
            continue
        except Exception:  # pragma: no cover
            logger.exception("Failed to instrument %s", module)

    logger.info("OpenTelemetry tracing enabled → %s", endpoint)
