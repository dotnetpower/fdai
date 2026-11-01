"""Load and resolve the complete 12-category, 867-table Azure Monitor Log Analytics catalog.

Covers all 12 public Log Analytics categories and 867 resource/diagnostic tables
published by Microsoft Learn. Read-only metadata only; never grants execution or
mutation authority.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fdai.delivery.repo_assets import repo_asset_root

_MONITOR_LOG_CATALOG_REL_PATH: Final[Path] = Path(
    "rule-catalog/collected/azure-monitor/log-tables.json"
)
_VALID_OWNERS: Final[frozenset[str]] = frozenset({"Huginn", "Heimdall", "Njord", "Vidar"})


@dataclass(frozen=True, slots=True)
class MonitorLogTableSpec:
    """Metadata and schema contract for one public Azure Monitor Log Analytics table."""

    table_name: str
    categories: tuple[str, ...]
    primary_category: str
    owner_agent: str
    time_column: str
    resource_id_columns: tuple[str, ...]
    allowed_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("MonitorLogTableSpec.table_name MUST be non-empty")
        if not self.categories or any(not c.strip() for c in self.categories):
            raise ValueError("MonitorLogTableSpec.categories MUST be non-empty")
        if self.primary_category not in self.categories:
            raise ValueError("MonitorLogTableSpec.primary_category MUST belong to categories")
        if self.owner_agent not in _VALID_OWNERS:
            raise ValueError(
                f"MonitorLogTableSpec.owner_agent MUST be one of {sorted(_VALID_OWNERS)}"
            )
        if not self.time_column.strip() or not self.resource_id_columns:
            raise ValueError("MonitorLogTableSpec time_column and resource_id_columns are required")
        if not self.allowed_columns or any(not col.strip() for col in self.allowed_columns):
            raise ValueError("MonitorLogTableSpec.allowed_columns MUST be non-empty")


@dataclass(frozen=True, slots=True)
class MonitorLogPublicCatalog:
    """In-memory index over all 12 categories and 867 Azure Monitor Log Analytics tables."""

    schema_version: str
    source: str
    categories: Mapping[str, int]
    tables: Mapping[str, MonitorLogTableSpec]
    folded_lookup: Mapping[str, str]

    @property
    def total_categories(self) -> int:
        return len(self.categories)

    @property
    def total_tables(self) -> int:
        return len(self.tables)

    def get_table(self, table_name: str) -> MonitorLogTableSpec:
        """Resolve a Log Analytics table by exact or case-insensitive name."""
        if not isinstance(table_name, str) or not table_name.strip():
            raise KeyError("Monitor Log table_name MUST be non-empty")
        clean = table_name.strip()
        if clean in self.tables:
            return self.tables[clean]
        canonical = self.folded_lookup.get(clean.casefold())
        if canonical is None:
            raise KeyError(f"Unknown Azure Monitor Log Analytics table: {table_name!r}")
        return self.tables[canonical]

    def tables_for_category(self, category: str) -> tuple[MonitorLogTableSpec, ...]:
        """Return all Log Analytics tables belonging to ``category`` in sorted order."""
        clean = category.strip().casefold() if isinstance(category, str) else ""
        return tuple(
            spec
            for _, spec in sorted(self.tables.items())
            if any(cat.casefold() == clean for cat in spec.categories)
        )


@functools.lru_cache(maxsize=2)
def load_monitor_log_catalog(repo_root: Path | None = None) -> MonitorLogPublicCatalog:
    """Load and validate the 12-category, 867-table Azure Monitor Log Analytics catalog."""
    root = repo_root or repo_asset_root()
    catalog_path = root / _MONITOR_LOG_CATALOG_REL_PATH
    raw: dict[str, Any] = json.loads(catalog_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported Azure Monitor Log catalog schema_version")
    tables_dict: dict[str, MonitorLogTableSpec] = {}
    folded: dict[str, str] = {}
    for entry in raw.get("tables", ()):
        spec = MonitorLogTableSpec(
            table_name=str(entry["table_name"]),
            categories=tuple(str(c) for c in entry["categories"]),
            primary_category=str(entry["primary_category"]),
            owner_agent=str(entry["owner_agent"]),
            time_column=str(entry["time_column"]),
            resource_id_columns=tuple(str(c) for c in entry["resource_id_columns"]),
            allowed_columns=tuple(str(c) for c in entry["allowed_columns"]),
        )
        tables_dict[spec.table_name] = spec
        folded[spec.table_name.casefold()] = spec.table_name
    categories = {str(k): int(v) for k, v in raw.get("categories", {}).items()}
    return MonitorLogPublicCatalog(
        schema_version=str(raw["schema_version"]),
        source=str(raw["source"]),
        categories=categories,
        tables=tables_dict,
        folded_lookup=folded,
    )


__all__ = [
    "MonitorLogPublicCatalog",
    "MonitorLogTableSpec",
    "load_monitor_log_catalog",
]
