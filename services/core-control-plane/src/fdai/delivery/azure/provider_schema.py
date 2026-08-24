"""Parse one complete pinned Azure Bicep type index into global schema evidence."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fdai.delivery.provider_schema import (
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    ProviderSchemaType,
)
from fdai.rule_catalog.pipeline.collect.fetch import GitCloneFetcher
from fdai.rule_catalog.schema.source_manifest import FetchConfig, FetchKind

_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
_INDEX_LINK_PATTERN = re.compile(r"\[([^\]]+)]\(([^)#]+types\.md)(?:#[^)]*)?\)")
_PREVIEW_PATTERN = re.compile(r"(?:preview|beta|alpha|rc)", re.IGNORECASE)
_SCOPE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(readable|writable)\s+scope(?:\(s\))?"
    r"(?:\*\*)?\s*:?\s*(.*?)\s*$",
    re.IGNORECASE,
)
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class _VersionLink:
    api_version: str
    relative_path: str


class AzureBicepProviderSchemaParser:
    """Normalize all resource headings from one pinned generated Bicep corpus."""

    def __init__(self, *, min_type_count: int = 1, max_type_count: int = 10_000) -> None:
        if min_type_count < 1 or max_type_count < min_type_count:
            raise ValueError("provider schema type bounds are invalid")
        self._min_type_count = min_type_count
        self._max_type_count = max_type_count

    def parse(self, *, tree_root: Path, source_revision: str) -> ProviderSchemaSnapshot:
        """Parse a complete tree or fail without producing a partial snapshot."""

        if not _REVISION_PATTERN.fullmatch(source_revision):
            raise ProviderSchemaError("Azure Bicep source revision MUST be immutable lowercase hex")
        root = tree_root.resolve()
        index_path = root / "generated" / "index.md"
        try:
            lines = index_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ProviderSchemaError("Azure Bicep generated/index.md is unavailable") from exc
        versions_by_type = _parse_index(lines)
        if not self._min_type_count <= len(versions_by_type) <= self._max_type_count:
            raise ProviderSchemaError(
                "Azure Bicep type count is outside configured complete-corpus bounds"
            )

        identities = {resource_type.casefold() for resource_type in versions_by_type}
        types: list[ProviderSchemaType] = []
        for authored_type, version_links in versions_by_type.items():
            resource_type = authored_type.casefold()
            stable = tuple(
                sorted(
                    link.api_version
                    for link in version_links
                    if not _PREVIEW_PATTERN.search(link.api_version)
                )
            )
            preview = tuple(
                sorted(
                    link.api_version
                    for link in version_links
                    if _PREVIEW_PATTERN.search(link.api_version)
                )
            )
            preferred = stable[-1] if stable else preview[-1]
            selected = next(link for link in version_links if link.api_version == preferred)
            document = _bounded_document(root, index_path.parent, selected.relative_path)
            readable, writable, scope_available = _parse_scopes(
                document,
                resource_type=authored_type,
                api_version=preferred,
            )
            parent_candidate = resource_type.rsplit("/", maxsplit=1)[0]
            parent_type = parent_candidate if parent_candidate in identities else None
            types.append(
                ProviderSchemaType(
                    resource_type=resource_type,
                    stable_api_versions=stable,
                    preview_api_versions=preview,
                    preferred_api_version=preferred,
                    source_document=document.relative_to(root).as_posix(),
                    parent_type=parent_type,
                    readable_scopes=readable,
                    writable_scopes=writable,
                    scope_evidence_available=scope_available,
                )
            )
        return ProviderSchemaSnapshot.build(
            provider="azure",
            source_revision=source_revision,
            types=tuple(types),
        )


class LocalAzureBicepProviderSchemaSource:
    """Read a mounted primary, mirror, or signed-offline Bicep tree."""

    def __init__(
        self,
        *,
        tree_root: Path,
        source_revision: str,
        parser: AzureBicepProviderSchemaParser,
    ) -> None:
        self._tree_root = tree_root
        self._source_revision = source_revision
        self._parser = parser

    async def collect(self) -> ProviderSchemaSnapshot:
        return await asyncio.to_thread(
            self._parser.parse,
            tree_root=self._tree_root,
            source_revision=self._source_revision,
        )


class GitAzureBicepProviderSchemaSource:
    """Resolve one remote ref, fetch that exact SHA, then parse its complete generated tree."""

    def __init__(
        self,
        *,
        repo_url: str,
        revision_ref: str,
        parser: AzureBicepProviderSchemaParser,
        timeout_seconds: float = 120.0,
        revision_resolver: Callable[[str, str, float], str] | None = None,
        tree_fetcher: Callable[[str, str, Path, float], Path] | None = None,
    ) -> None:
        _validate_git_source(repo_url, revision_ref, timeout_seconds=timeout_seconds)
        self._repo_url = repo_url
        self._revision_ref = revision_ref
        self._parser = parser
        self._timeout_seconds = timeout_seconds
        self._revision_resolver = revision_resolver or _resolve_git_revision
        self._tree_fetcher = tree_fetcher or _fetch_git_tree

    async def collect(self) -> ProviderSchemaSnapshot:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> ProviderSchemaSnapshot:
        revision = (
            self._revision_ref
            if _REVISION_PATTERN.fullmatch(self._revision_ref)
            else self._revision_resolver(
                self._repo_url,
                self._revision_ref,
                self._timeout_seconds,
            )
        )
        if not _REVISION_PATTERN.fullmatch(revision):
            raise ProviderSchemaError(
                "resolved Azure Bicep revision is not immutable lowercase hex"
            )
        with tempfile.TemporaryDirectory(prefix="fdai-provider-schema-") as temporary:
            tree = self._tree_fetcher(
                self._repo_url,
                revision,
                Path(temporary),
                self._timeout_seconds,
            )
            return self._parser.parse(tree_root=tree, source_revision=revision)


def _parse_index(lines: list[str]) -> dict[str, tuple[_VersionLink, ...]]:
    links_by_type: dict[str, list[_VersionLink]] = {}
    current_type: str | None = None
    for line in lines:
        if line.startswith("### "):
            current_type = line[4:].strip()
            if not current_type:
                raise ProviderSchemaError("Azure Bicep index contains an empty type heading")
            if current_type.casefold() in {item.casefold() for item in links_by_type}:
                raise ProviderSchemaError(f"Azure Bicep index repeats type: {current_type}")
            links_by_type[current_type] = []
            continue
        match = _INDEX_LINK_PATTERN.search(line)
        if match is None:
            continue
        if current_type is None:
            raise ProviderSchemaError("Azure Bicep index link appears before a type heading")
        api_version, relative_path = (item.strip() for item in match.groups())
        links_by_type[current_type].append(
            _VersionLink(api_version=api_version, relative_path=relative_path)
        )
    empty = sorted(resource_type for resource_type, links in links_by_type.items() if not links)
    if empty:
        raise ProviderSchemaError(
            "Azure Bicep index types have no API versions: " + ", ".join(empty[:5])
        )
    normalized: dict[str, tuple[_VersionLink, ...]] = {}
    for resource_type, links in links_by_type.items():
        versions = [link.api_version for link in links]
        if len(versions) != len(set(versions)):
            raise ProviderSchemaError(f"Azure Bicep index repeats API version: {resource_type}")
        normalized[resource_type] = tuple(links)
    return normalized


def _bounded_document(root: Path, index_root: Path, relative_path: str) -> Path:
    candidate = (index_root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ProviderSchemaError("Azure Bicep index references an unavailable bounded document")
    return candidate


def _parse_scopes(
    document: Path,
    *,
    resource_type: str,
    api_version: str,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    try:
        lines = document.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProviderSchemaError("Azure Bicep preferred schema document is unavailable") from exc
    block = _resource_block(lines, resource_type=resource_type, api_version=api_version)
    if block is None:
        return (), (), False
    values: dict[str, tuple[str, ...]] = {}
    for line in block:
        match = _SCOPE_PATTERN.match(line)
        if match is None:
            continue
        kind, raw = match.groups()
        normalized = raw.replace("`", "").replace("*", "").strip()
        values[kind.casefold()] = (
            ()
            if normalized.casefold() in {"", "none", "n/a"}
            else tuple(
                sorted({item.strip() for item in re.split(r"[,|]", normalized) if item.strip()})
            )
        )
    if not {"readable", "writable"} <= values.keys():
        return (), (), False
    return values["readable"], values["writable"], True


def _resource_block(
    lines: list[str],
    *,
    resource_type: str,
    api_version: str,
) -> list[str] | None:
    expected = resource_type.casefold()
    start: int | None = None
    level: int | None = None
    for index, line in enumerate(lines):
        match = _HEADING_PATTERN.match(line)
        if match is None:
            continue
        heading_level = len(match.group(1))
        heading = match.group(2).casefold()
        if start is None:
            if expected in heading and api_version.casefold() in heading:
                start = index + 1
                level = heading_level
            continue
        if heading_level <= (level or 6):
            return lines[start:index]
    return None if start is None else lines[start:]


def _validate_git_source(repo_url: str, revision_ref: str, *, timeout_seconds: float) -> None:
    parsed = urllib.parse.urlparse(repo_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("provider schema Git source MUST be credential-free HTTPS")
    if not revision_ref.strip() or not revision_ref.isascii():
        raise ValueError("provider schema Git revision ref MUST be non-empty ASCII")
    if timeout_seconds <= 0:
        raise ValueError("provider schema Git timeout MUST be positive")


def _resolve_git_revision(repo_url: str, revision_ref: str, timeout_seconds: float) -> str:
    git_binary = shutil.which("git")
    if git_binary is None:
        raise ProviderSchemaError("provider schema Git executable is unavailable")
    process = subprocess.run(  # noqa: S603 - fixed binary and argv; no shell.
        [git_binary, "ls-remote", "--exit-code", repo_url, revision_ref],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if process.returncode != 0:
        raise ProviderSchemaError("provider schema Git revision lookup failed")
    revisions = {line.split(maxsplit=1)[0] for line in process.stdout.splitlines() if line.strip()}
    if len(revisions) != 1:
        raise ProviderSchemaError("provider schema Git revision lookup is ambiguous")
    return revisions.pop().casefold()


def _fetch_git_tree(
    repo_url: str,
    revision: str,
    destination: Path,
    timeout_seconds: float,
) -> Path:
    result = GitCloneFetcher(timeout_seconds=timeout_seconds).fetch(
        config=FetchConfig(
            kind=FetchKind.GIT,
            repo=repo_url,
            revision=revision,
        ),
        dest_root=destination,
    )
    return result.tree_root


__all__ = [
    "AzureBicepProviderSchemaParser",
    "GitAzureBicepProviderSchemaSource",
    "LocalAzureBicepProviderSchemaSource",
]
