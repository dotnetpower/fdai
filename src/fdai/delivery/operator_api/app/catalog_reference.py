"""Fail-closed repository catalog loading for read-only reference routes."""

from __future__ import annotations

import logging
from pathlib import Path

from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog, load_mcsb_catalogs
from fdai.shared.contracts.models import BestPractice

_LOGGER = logging.getLogger(__name__)


def load_best_practice_reference(repo_root: Path) -> tuple[BestPractice, ...]:
    """Load validated Best Practice definitions without claiming runtime evidence."""

    root = repo_root / "rule-catalog" / "best-practices"
    if not root.is_dir():
        return ()
    try:
        return load_best_practice_catalog(root, strict=False)
    except Exception:  # noqa: BLE001
        _LOGGER.error("best_practice_catalog_load_failed", exc_info=True)
        return ()


def load_mcsb_reference(repo_root: Path) -> tuple[McsbCatalog, ...]:
    """Load versioned MCSB definitions without claiming runtime compliance."""

    root = repo_root / "rule-catalog" / "compliance" / "mcsb"
    if not root.is_dir():
        return ()
    try:
        return load_mcsb_catalogs(root, strict=False)
    except Exception:  # noqa: BLE001
        _LOGGER.error("mcsb_catalog_load_failed", exc_info=True)
        return ()


__all__ = ["load_best_practice_reference", "load_mcsb_reference"]
