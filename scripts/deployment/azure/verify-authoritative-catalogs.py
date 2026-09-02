#!/usr/bin/env python3
"""Verify immutable repository catalog projections through PostgreSQL readback."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig


def _materializer(repo_root: Path) -> ModuleType:
    path = repo_root / "scripts/deployment/local/materialize-authoritative-catalogs.py"
    spec = importlib.util.spec_from_file_location("materialize_authoritative_catalogs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("authoritative catalog materializer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def verify(repo_root: Path) -> int:
    """Compare immutable expected projections with authoritative PostgreSQL state."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    module = _materializer(repo_root)
    expected = cast(dict[str, dict[str, Any]], module.catalog_snapshots(repo_root))
    dynamic_keys = {
        module.ONTOLOGY_EVIDENCE_HEALTH_KEY,
        module.ONTOLOGY_RELEASE_DIFF_KEY,
    }
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    verified = 0
    for key, payload in expected.items():
        if key in dynamic_keys:
            continue
        observed = await store.read_state(key)
        if observed is None or dict(observed) != payload:
            raise RuntimeError(f"authoritative catalog readback mismatch: {key}")
        verified += 1
    return verified


def main() -> int:
    """Verify catalog state without printing deployment or database identifiers."""
    repo_root = Path(__file__).resolve().parents[3]
    verified = asyncio.run(verify(repo_root))
    print(f"authoritative PostgreSQL catalog readback verified: {verified} projections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
