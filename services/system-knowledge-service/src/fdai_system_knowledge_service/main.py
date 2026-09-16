"""System Knowledge Service process entry point."""

from __future__ import annotations

import os

from fdai_service_contracts import ServiceDescriptor, ServiceKind, record_runtime_scope_receipt

from fdai_system_knowledge_service.application import create_app, create_runtime
from fdai_system_knowledge_service.config import SystemKnowledgeSettings
from fdai_system_knowledge_service.server import serve

SERVICE = ServiceDescriptor(
    service_id="system-knowledge-service",
    distribution="fdai-system-knowledge-service",
    image="fdai-system-knowledge-service",
    entrypoint="fdai-system-knowledge-service",
    kind=ServiceKind.HTTP_API,
)


def main() -> int:
    """Serve the configured System Knowledge Service."""

    record_runtime_scope_receipt(SERVICE, os.environ)
    settings = SystemKnowledgeSettings.parse(os.environ)
    return serve(create_app(runtime=create_runtime(settings)), settings)


__all__ = ["SERVICE", "create_app", "main"]
