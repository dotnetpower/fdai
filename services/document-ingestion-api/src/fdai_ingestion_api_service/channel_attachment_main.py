"""Internal channel attachment intake process entry point."""

import os

from fdai_service_contracts import ServiceDescriptor, ServiceKind

from fdai_ingestion_api_service.channel_attachment_production import (
    build_channel_attachment_application,
)
from fdai_ingestion_api_service.server import serve

SERVICE = ServiceDescriptor(
    service_id="document-ingestion-api",
    distribution="fdai-document-ingestion-api",
    image="fdai-document-ingestion-api",
    entrypoint="fdai-document-channel-intake",
    kind=ServiceKind.HTTP_API,
)


def main() -> int:
    """Serve the internal attachment workload from the ingestion distribution."""

    return serve(build_channel_attachment_application(os.environ))
