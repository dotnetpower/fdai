"""Isolated Executor service entry point."""

from fdai_service_contracts import ServiceDescriptor, ServiceKind

SERVICE = ServiceDescriptor(
    service_id="isolated-executor",
    distribution="fdai-isolated-executor-service",
    image="fdai-isolated-executor",
    entrypoint="fdai-isolated-executor-service",
    kind=ServiceKind.EVENT_CONSUMER,
    executor_authority=True,
)


def main() -> int:
    """Start the service-owned isolated Executor process."""
    from fdai_executor_service.cli import main as run

    return run()
