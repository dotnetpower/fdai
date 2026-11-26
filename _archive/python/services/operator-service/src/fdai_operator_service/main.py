"""Operator Service process entry point and public ASGI factory."""

from __future__ import annotations

import os
from collections.abc import Mapping

from fdai_service_contracts import ServiceDescriptor, ServiceKind, record_runtime_scope_receipt

from fdai_operator_service.application import create_app as build_application
from fdai_operator_service.contracts import AsgiApplication
from fdai_operator_service.production import serve

SERVICE = ServiceDescriptor(
    service_id="operator-service",
    distribution="fdai-operator-service",
    image="fdai-operator-service",
    entrypoint="fdai-operator-service",
    kind=ServiceKind.HTTP_API,
)


def create_app(environ: Mapping[str, str] | None = None) -> AsgiApplication:
    """Bind one runtime-scope receipt before composing the ASGI application."""
    values = dict(os.environ if environ is None else environ)
    receipt = record_runtime_scope_receipt(SERVICE, values)
    values["FDAI_RUNTIME_SCOPE_RECEIPT_DIGEST"] = receipt.receipt_digest
    return build_application(values)


def main() -> int:
    """Serve the production Operator API."""
    return serve("fdai_operator_service.main:create_app")
