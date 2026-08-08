"""Fetcher Protocol + built-in implementations.

The pipeline uses a fetch adapter picked by :class:`FetchKind`. Three
implementations ship today:

- :class:`LocalDirectoryFetcher` - copies a filesystem tree into the
  snapshot directory. Used by tests and by hand-authored sources that
  live inside this repo.
- :class:`GitCloneFetcher` - ``git clone --depth 1`` at the pinned
  revision, then copies the requested ``subpath`` (or whole tree). Real
  networked adapter used for OSS sources (Gatekeeper library, Checkov,
  tfsec, ...).
- :class:`HttpDownloadFetcher` - download a single URL over ``http(s)``
  or ``file://``, verify against the manifest's ``expected_sha256`` and
  drop the file into the snapshot tree. Used for tarball / single-file
  sources.

Every fetcher returns a :class:`FetchResult` describing the local
directory the pipeline will hash + snapshot.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from fdai.rule_catalog.schema.source_manifest import FetchConfig, FetchKind


class FetchError(RuntimeError):
    """Raised when a fetch cannot complete deterministically."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Local directory + resolved revision returned by a fetcher.

    ``resolved_revision`` is the immutable identifier the pipeline records
    on the snapshot's provenance (git commit sha for git, source path for
    local, expected_sha256 for http). It maps 1:1 into
    :attr:`fdai.shared.contracts.models.Provenance.resolved_ref`
    on any downstream rule authored from this snapshot - the two field
    names differ because ``resolved_revision`` is the collector's
    computed value while ``resolved_ref`` is the rule author's declared
    origin; the value is the same string.
    """

    tree_root: Path
    resolved_revision: str


@runtime_checkable
class Fetcher(Protocol):
    """One fetch adapter.

    ``fetch`` MUST populate ``dest_root`` with the source tree the caller
    will hash + snapshot. It MAY create subdirectories under ``dest_root``
    but MUST NOT touch anything outside it.
    """

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult: ...


# ---------------------------------------------------------------------------
# Local (fixture / hand-authored) fetcher
# ---------------------------------------------------------------------------


class LocalDirectoryFetcher(Fetcher):
    """Copy a filesystem tree into the snapshot dir.

    Absolute paths are respected; relative paths are resolved against
    the repo root supplied at construction. The whole tree is copied so
    subsequent stages can hash a stable byte sequence.
    """

    def __init__(self, *, repo_root: Path) -> None:
        if not repo_root.is_dir():
            raise ValueError(f"repo_root MUST be a directory; got {repo_root!r}")
        self._repo_root = repo_root

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:
        if config.kind is not FetchKind.LOCAL:
            raise FetchError(f"LocalDirectoryFetcher does not handle kind={config.kind}")
        if config.path is None:  # pragma: no cover - schema enforces
            raise FetchError("LocalDirectoryFetcher requires fetch.path")

        source = Path(config.path)
        if not source.is_absolute():
            source = (self._repo_root / source).resolve()
        if not source.exists():
            raise FetchError(f"local source not found: {source}")

        dest_root.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target = dest_root / source.name
            shutil.copy2(source, target)
        else:
            for entry in source.iterdir():
                dest = dest_root / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)
        return FetchResult(tree_root=dest_root, resolved_revision=str(source))


# ---------------------------------------------------------------------------
# Git clone fetcher
# ---------------------------------------------------------------------------


class GitCloneFetcher(Fetcher):
    """Shallow-clone at a pinned SHA, then copy the requested subtree.

    Uses ``git clone --depth 1 --branch <sha>`` when possible; falls back
    to ``fetch --depth 1 <sha>`` for hosts that reject a branch=sha shape.
    A malformed revision (mutable ref) is rejected earlier by
    ``SourceManifest`` - this class only executes what the manifest
    validated.
    """

    def __init__(self, *, git_binary: str = "git", timeout_seconds: float = 120.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        self._git = git_binary
        self._timeout = timeout_seconds

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:
        if config.kind is not FetchKind.GIT:
            raise FetchError(f"GitCloneFetcher does not handle kind={config.kind}")
        if config.repo is None or config.revision is None:  # pragma: no cover - schema enforces
            raise FetchError("GitCloneFetcher requires fetch.repo + fetch.revision")

        dest_root.mkdir(parents=True, exist_ok=True)
        checkout_dir = dest_root / "_clone"

        try:
            self._run([self._git, "init", "--quiet"], cwd=checkout_dir, mkdir=True)
            self._run([self._git, "remote", "add", "origin", config.repo], cwd=checkout_dir)
            self._run(
                [
                    self._git,
                    "fetch",
                    "--depth",
                    "1",
                    "--no-tags",
                    "--filter=blob:none",
                    "origin",
                    config.revision,
                ],
                cwd=checkout_dir,
            )
            self._run([self._git, "checkout", "--quiet", "FETCH_HEAD"], cwd=checkout_dir)
        except FetchError:
            raise
        except subprocess.SubprocessError as exc:
            raise FetchError(f"git operation failed: {exc}") from exc

        source_tree = checkout_dir if config.subpath is None else checkout_dir / config.subpath
        if not source_tree.exists():
            raise FetchError(f"subpath {config.subpath!r} does not exist in cloned tree")

        # Copy the subtree next to the clone dir so hash + snapshot don't
        # include the .git metadata.
        target_root = dest_root / "tree"
        target_root.mkdir(parents=True, exist_ok=True)
        if source_tree.is_file():
            shutil.copy2(source_tree, target_root / source_tree.name)
        else:
            for entry in source_tree.iterdir():
                if entry.name == ".git":
                    continue
                dest = target_root / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)

        # Drop the clone dir now that we have the clean tree.
        shutil.rmtree(checkout_dir, ignore_errors=True)
        return FetchResult(tree_root=target_root, resolved_revision=config.revision)

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        mkdir: bool = False,
    ) -> None:
        if mkdir:
            cwd.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(  # noqa: S603 - argv is a list, not shell.
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise FetchError(
                f"{' '.join(argv)} failed with exit={proc.returncode}:\n{proc.stderr.strip()}"
            )


# ---------------------------------------------------------------------------
# HTTP download fetcher
# ---------------------------------------------------------------------------


_ALLOWED_HTTP_SCHEMES = frozenset({"http", "https", "file"})


class HttpDownloadFetcher(Fetcher):
    """Download one URL, verify its sha256, drop it in the snapshot tree.

    The manifest MUST carry ``expected_sha256``; the fetcher rejects the
    download when the computed hash differs so the resolved revision on
    the snapshot is always the operator-declared one. Only ``http``,
    ``https``, and ``file`` URL schemes are honored - anything else
    (``ftp``, ``data``, custom) is refused up front to keep the surface
    predictable and to make tests offline-safe via ``file://`` URLs.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 120.0,
        chunk_bytes: int = 65_536,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if chunk_bytes <= 0:
            raise ValueError("chunk_bytes MUST be > 0")
        self._timeout = timeout_seconds
        self._chunk = chunk_bytes

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:
        if config.kind is not FetchKind.HTTP:
            raise FetchError(f"HttpDownloadFetcher does not handle kind={config.kind}")
        if (
            config.url is None or config.expected_sha256 is None
        ):  # pragma: no cover - schema enforces
            raise FetchError("HttpDownloadFetcher requires fetch.url + fetch.expected_sha256")

        scheme = urllib.parse.urlparse(config.url).scheme.lower()
        if scheme not in _ALLOWED_HTTP_SCHEMES:
            raise FetchError(
                f"URL scheme {scheme!r} is not allowed (accepted: {sorted(_ALLOWED_HTTP_SCHEMES)})"
            )

        dest_root.mkdir(parents=True, exist_ok=True)
        # Pick a stable output filename - the last path segment when it
        # looks like a filename, else a synthetic ``payload`` so the
        # snapshot layout stays predictable.
        filename = Path(urllib.parse.urlparse(config.url).path).name or "payload"
        target = dest_root / filename

        digest = hashlib.sha256()
        try:
            with (
                urllib.request.urlopen(  # noqa: S310 - scheme allow-list enforced above.
                    config.url, timeout=self._timeout
                ) as response,
                target.open("wb") as sink,
            ):
                while True:
                    chunk = response.read(self._chunk)
                    if not chunk:
                        break
                    digest.update(chunk)
                    sink.write(chunk)
        except OSError as exc:
            raise FetchError(f"http download failed: {exc}") from exc

        actual_sha = digest.hexdigest()
        if actual_sha != config.expected_sha256:
            # Never leave a mis-hashed payload sitting on disk - a later
            # tool could treat it as valid.
            target.unlink(missing_ok=True)
            raise FetchError(
                f"sha256 mismatch: expected={config.expected_sha256} actual={actual_sha}"
            )

        return FetchResult(tree_root=dest_root, resolved_revision=config.expected_sha256)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def build_fetcher(kind: FetchKind, *, repo_root: Path) -> Fetcher:
    """Return the default fetcher for a manifest kind.

    Composition-root helper. Forks can replace individual fetchers by
    swapping the dispatch in their own composition root.
    """
    if kind is FetchKind.LOCAL:
        return LocalDirectoryFetcher(repo_root=repo_root)
    if kind is FetchKind.GIT:
        return GitCloneFetcher()
    if kind is FetchKind.HTTP:
        return HttpDownloadFetcher()
    raise FetchError(f"no default fetcher registered for kind={kind}")


__all__ = [
    "FetchError",
    "FetchResult",
    "Fetcher",
    "GitCloneFetcher",
    "HttpDownloadFetcher",
    "LocalDirectoryFetcher",
    "build_fetcher",
]
