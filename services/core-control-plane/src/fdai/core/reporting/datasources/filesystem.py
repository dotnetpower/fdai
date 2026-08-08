"""Filesystem-manifest datasource - inventory of files under a root directory.

Read-only projection used for demo / operations-console diagnostics.
Never modifies the filesystem, never opens files (only ``stat``).

Query parameters (``spec.parameters``):

- ``pattern`` (str, default ``"*"``): filename glob (``fnmatch``
  semantics) applied to each entry. Absolute paths and ``..`` traversal
  are rejected up-front.
- ``projection`` (str, default ``rows``): ``rows`` (path + size + mtime)
  or ``count_total`` (scalar).

Constructor options:

- ``root`` (Path, required): the enumeration boundary.
- ``include_hidden`` (bool, default ``False``): when False, entries
  whose name starts with ``.`` (dotfiles like ``.git``, ``.env``) are
  skipped. This is the safer default because a fork that hands the
  reporting subsystem a repository root does NOT want to expose its
  ``.git`` / ``.env`` contents to a dashboard.

Safety:

- Symlinks are NOT followed (``os.walk(followlinks=False)``) so a link
  cycle cannot loop the walk and a link that resolves outside the
  configured root cannot smuggle a foreign path into the response.
- The walk is capped at :data:`_MAX_ENTRIES` entries.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec

_MAX_ENTRIES = 5000


class FilesystemManifestDataSource:
    """Enumerate files under a fixed root directory."""

    __slots__ = ("_name", "_root", "_include_hidden")

    def __init__(
        self,
        *,
        root: Path,
        name: str = "filesystem_manifest",
        include_hidden: bool = False,
    ) -> None:
        self._name = name
        self._root = root.resolve()
        self._include_hidden = bool(include_hidden)

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
        rejection = _reject_bad_pattern(pattern)
        if rejection is not None:
            return DataSet(metadata={"error": rejection})
        projection = str(params.get("projection", "rows"))
        entries: list[dict[str, Any]] = []
        # os.walk with followlinks=False avoids two classes of bug:
        #   1. symlink loop -> infinite recursion in Path.rglob.
        #   2. a symlink whose target lives outside the configured root
        #      would still be resolved back inside by rglob and could
        #      appear in the manifest with a foreign path.
        for dirpath, dirnames, filenames in os.walk(self._root, followlinks=False):
            if not self._include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                if not self._include_hidden and filename.startswith("."):
                    continue
                full = Path(dirpath) / filename
                try:
                    rel_posix = full.relative_to(self._root).as_posix()
                except ValueError:
                    continue
                if not _match(rel_posix, filename, pattern):
                    continue
                # Symlinks are not followed, but a plain file whose
                # path is itself a link to elsewhere would still be
                # honored by stat - filter defensively.
                if full.is_symlink():
                    continue
                try:
                    stat_result = full.stat()
                except OSError:
                    continue
                entries.append(
                    {
                        "path": rel_posix,
                        "size": stat_result.st_size,
                        "at": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(),
                    }
                )
                if len(entries) >= _MAX_ENTRIES:
                    break
            if len(entries) >= _MAX_ENTRIES:
                break
        entries.sort(key=lambda entry: entry["path"])
        if projection == "count_total":
            return DataSet(scalar=len(entries))
        return DataSet(
            columns=("path", "size", "at"),
            rows=tuple(entries),
            metadata={"root": str(self._root)},
        )


def _match(rel_posix: str, basename: str, pattern: str) -> bool:
    """Return True when ``rel_posix`` matches ``pattern``.

    Match rules (evaluated in order):

    - Match-all sentinels (``*`` / ``**`` / ``**/*`` / ``**/**``) match
      every file in the walk.
    - Full-path fnmatch (``/`` is literal, no ``**`` expansion):
      ``sub/*.txt`` matches ``sub/b.txt`` but not ``a.txt``.
    - Basename convenience: a pattern with no ``/`` also matches the
      file basename at any depth, so ``*.txt`` finds ``sub/b.txt`` too.
    """
    if pattern in ("*", "**", "**/*", "**/**"):
        return True
    if fnmatch.fnmatch(rel_posix, pattern):
        return True
    if "/" not in pattern and fnmatch.fnmatch(basename, pattern):
        return True
    return False


def _reject_bad_pattern(pattern: str) -> str | None:
    """Return a human message if ``pattern`` is unsafe, else ``None``.

    Absolute paths (posix or Windows drive-letter) let a caller
    circumvent the configured root; ``..`` lets a caller escape via
    parent traversal. Both are hard-rejected.
    """
    if not pattern:
        return "pattern rejected: empty"
    if PurePosixPath(pattern).is_absolute() or PureWindowsPath(pattern).is_absolute():
        return "pattern rejected: absolute path"
    parts = Path(pattern).parts
    if ".." in parts:
        return "pattern rejected: contains '..'"
    return None


__all__ = ["FilesystemManifestDataSource"]
