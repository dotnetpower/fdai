"""Document Processing Worker service entry point."""

from fdai_service_contracts import ServiceDescriptor, ServiceKind

from fdai_document_worker_service.application import run_worker

SERVICE = ServiceDescriptor(
    service_id="document-processing-worker",
    distribution="fdai-document-processing-worker",
    image="fdai-document-processing-worker",
    entrypoint="fdai-document-processing-worker",
    kind=ServiceKind.EVENT_CONSUMER,
)


def main() -> int:
    """Start the document worker through the service-owned entry point."""
    return run_worker()
