"""Operator Service process entry point and public ASGI factory."""

from fdai_service_contracts import ServiceDescriptor, ServiceKind

from fdai_operator_service.application import create_app as create_app
from fdai_operator_service.production import serve

SERVICE = ServiceDescriptor(
    service_id="operator-service",
    distribution="fdai-operator-service",
    image="fdai-operator-service",
    entrypoint="fdai-operator-service",
    kind=ServiceKind.HTTP_API,
)


def main() -> int:
    """Serve the production Operator API."""
    return serve("fdai_operator_service.main:create_app")
