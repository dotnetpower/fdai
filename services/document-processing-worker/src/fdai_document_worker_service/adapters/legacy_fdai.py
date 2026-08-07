"""Compatibility adapter for the existing FDAI document worker implementation."""

from __future__ import annotations

from collections.abc import Mapping


def run_worker(_environ: Mapping[str, str]) -> int:
    """Delegate process execution to the legacy worker implementation."""
    from fdai.delivery.ingestion_gateway.worker import main

    return main()
