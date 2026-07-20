"""Git-tracked source allowlist and blob freshness validation."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from fdai.shared.providers.behavior_knowledge import (
    BehaviorFreshness,
    BehaviorSource,
    BehaviorSourceValidator,
)


class GitTrackedSourceValidator(BehaviorSourceValidator):
    """Validate citations against ``git ls-files`` and working-tree blobs.

    Only tracked paths may be hashed. Ignored, generated, secret-bearing, and
    untracked files therefore cannot enter behavior evidence accidentally.
    Missing Git metadata fails closed as untracked and stale.
    """

    def __init__(self, repository_root: Path | str) -> None:
        self._root = Path(repository_root).resolve()
        self._tracked_paths: frozenset[str] | None = None
        self._lock = asyncio.Lock()

    async def validate(self, source: BehaviorSource) -> BehaviorFreshness:
        current = await self.current_blob_sha(source.path)
        return BehaviorFreshness(
            fresh=current == source.blob_sha,
            tracked=current is not None,
            current_blob_sha=current,
        )

    async def current_blob_sha(self, relative_path: str) -> str | None:
        tracked = await self.tracked_paths()
        if relative_path not in tracked:
            return None
        output = await self._git("hash-object", "--", relative_path)
        if output is None:
            return None
        value = output.decode("ascii", errors="strict").strip()
        return value or None

    async def head_commit(self) -> str | None:
        output = await self._git("rev-parse", "HEAD")
        if output is None:
            return None
        value = output.decode("ascii", errors="strict").strip()
        return value or None

    async def tracked_paths(self) -> frozenset[str]:
        if self._tracked_paths is not None:
            return self._tracked_paths
        async with self._lock:
            if self._tracked_paths is None:
                output = await self._git("ls-files", "-z", "--")
                if output is None:
                    self._tracked_paths = frozenset()
                else:
                    self._tracked_paths = frozenset(
                        item.decode("utf-8") for item in output.split(b"\0") if item
                    )
        return self._tracked_paths

    async def _git(self, *args: str) -> bytes | None:
        executable = shutil.which("git")
        if executable is None:
            return None

        def run() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(  # noqa: S603 - fixed executable, no shell
                (executable, *args),
                cwd=self._root,
                check=False,
                capture_output=True,
            )

        completed = await asyncio.to_thread(run)
        return completed.stdout if completed.returncode == 0 else None


__all__ = ["GitTrackedSourceValidator"]
