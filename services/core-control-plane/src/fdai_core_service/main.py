"""Core Control Plane service entry point."""

from fdai_service_contracts import ServiceDescriptor, ServiceKind

SERVICE = ServiceDescriptor(
    service_id="core-control-plane",
    distribution="fdai-core-control-plane",
    image="fdai-core-control-plane",
    entrypoint="fdai-core-control-plane",
    kind=ServiceKind.CONTROL_PLANE,
)


def main() -> int:
    """Start the existing Core runtime through the service-owned entry point."""
    from fdai.runtime.bootstrap import main as run

    return run()
