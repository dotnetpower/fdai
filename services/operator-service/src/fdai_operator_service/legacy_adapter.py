"""Sole compatibility adapter for the existing FDAI Operator implementation."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.contracts import AsgiApplication
from fdai_operator_service.routes import DelegatingApplication


def create_app(environ: Mapping[str, str]) -> AsgiApplication:
    """Build and wrap the existing production application behind service contracts."""
    from fdai.delivery.operator_api.prod import build_prod_app

    return DelegatingApplication(build_prod_app(environ))
