"""Operator Service entry point and ASGI factory."""

from typing import Any

from fdai_service_contracts import ServiceDescriptor, ServiceKind

SERVICE = ServiceDescriptor(
    service_id="operator-service",
    distribution="fdai-operator-service",
    image="fdai-operator-service",
    entrypoint="fdai-operator-service",
    kind=ServiceKind.HTTP_API,
)


def create_app() -> Any:
    """Build the production Operator ASGI app through its owned entry point."""
    from fdai.delivery.operator_api.prod import app

    return app()


def main() -> int:
    """Serve the production Operator API."""
    import uvicorn

    uvicorn.run(
        "fdai_operator_service.main:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - Container App ingress terminates external HTTPS.
        port=8000,
    )
    return 0
