"""Document Ingestion API entry point and ASGI factory."""

from typing import Any

from fdai_service_contracts import ServiceDescriptor, ServiceKind

SERVICE = ServiceDescriptor(
    service_id="document-ingestion-api",
    distribution="fdai-document-ingestion-api",
    image="fdai-document-ingestion-api",
    entrypoint="fdai-document-ingestion-api",
    kind=ServiceKind.HTTP_API,
)


def create_app() -> Any:
    """Build the production ingestion ASGI app through its owned entry point."""
    from fdai.delivery.ingestion_gateway.prod import app

    return app()


def main() -> int:
    """Serve the production Document Ingestion API."""
    import uvicorn

    uvicorn.run(
        "fdai_ingestion_api_service.main:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - Container App ingress terminates external HTTPS.
        port=8000,
    )
    return 0
