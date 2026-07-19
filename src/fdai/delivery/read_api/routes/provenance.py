"""Read-projection provenance markers shared by local fixtures and routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEV_SEED_FIXTURE_SOURCE = "read-api-dev-seed"


def is_dev_seed_fixture(entry: Mapping[str, Any]) -> bool:
    """Return whether an audit entry belongs to the local read-API fixture."""
    return entry.get("fixture_source") == DEV_SEED_FIXTURE_SOURCE


__all__ = ["DEV_SEED_FIXTURE_SOURCE", "is_dev_seed_fixture"]
