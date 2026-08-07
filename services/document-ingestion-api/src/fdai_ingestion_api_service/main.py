"""Document Ingestion API process entry point."""

from fdai_service_contracts import ServiceDescriptor, ServiceKind

from fdai_ingestion_api_service.application import create_app as create_app
from fdai_ingestion_api_service.server import serve

SERVICE = ServiceDescriptor(
    service_id="document-ingestion-api",
    distribution="fdai-document-ingestion-api",
    image="fdai-document-ingestion-api",
    entrypoint="fdai-document-ingestion-api",
    kind=ServiceKind.HTTP_API,
)


def main() -> int:
    """Serve the production Document Ingestion API."""
    return serve(create_app())
