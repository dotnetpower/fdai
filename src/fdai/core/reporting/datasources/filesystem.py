"""Filesystem-manifest datasource - inventory of files under a root directory.

Read-only projection used for demo / operations-console diagnostics.
Never modifies the filesystem, never opens files (only ``stat``).

Query parameters (``spec.parameters``):

- ``pattern`` (str, default ``"*"``): glob pattern relative to the
  configured root. Refuses ``..`` traversal in the pattern.
- ``projection`` (str, default ``rows``): ``rows`` (path + size + mtime)
  or ``count_total`` (scalar).

The datasource carries its own root path (constructor argument), never
a caller-supplied one - the read-API surface accepts nothing that would
let a client escape the configured root.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec

_MAX_ENTRIES = 5000


class FilesystemManifestDataSource:
    """Enumerate files under a fixed root directory."""

    __slots__ = ("_name", "_root")

    def __init__(self, *, root: Path, name: str = "filesystem_manifest") -> None:
        self._name = name
        self._root = root.resolve()

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        del since, until, variables
        params = spec.parameters
        pattern = str(params.get("pattern", "*"))
        if ".." in Path(pattern).parts:
            return DataSet(metadata={"error": "pattern rejected: contains '..'"})
        projection = str(params.get("projection", "rows"))
        entries: list[dict[str, Any]] = []
        # rglob(pattern) matches recursively; guarded by _MAX_ENTRIES so a
        # huge root never blows up the response.
        for path in sorted(self._root.rglob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            # Defense in depth against symlinks pointing outside root.
            try:
                resolved.relative_to(self._root)
            except ValueError:
                continue
            entries.append(
                {
                    "path": str(resolved.relative_to(self._root)),
                    "size": resolved.stat().st_size,
                    "at": datetime.fromtimestamp(
                        resolved.stat().st_mtime, tz=UTC
                    ).isoformat(),
                }
            )
            if len(entries) >= _MAX_ENTRIES:
                break
        if projection == "count_total":
            return DataSet(scalar=len(entries))
        return DataSet(
            columns=("path", "size", "at"),
            rows=tuple(entries),
            metadata={"root": str(self._root)},
        )


__all__ = ["FilesystemManifestDataSource"]
