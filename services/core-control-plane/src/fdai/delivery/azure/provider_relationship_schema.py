"""Extract no-authority ARM relationship evidence from pinned Azure REST specifications."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.rule_catalog.pipeline.collect.fetch import GitCloneFetcher
from fdai.rule_catalog.schema.source_manifest import FetchConfig, FetchKind

_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESOURCE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.]+/[A-Za-z0-9][A-Za-z0-9./-]*$")
_HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put"})


@dataclass(frozen=True, slots=True)
class AzureArmIdReference:
    """One schema location that explicitly declares an ARM resource identifier."""

    source_document: str
    json_pointer: str
    allowed_resource_types: tuple[str, ...]
    unresolved_allowed_resources: tuple[str, ...]
    operation_paths: tuple[str, ...]
    source_resource_types: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        return bool(self.allowed_resource_types) and not self.unresolved_allowed_resources

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_document": self.source_document,
            "json_pointer": self.json_pointer,
            "resolution": "exact" if self.resolved else "unresolved",
            "allowed_resource_types": list(self.allowed_resource_types),
            "unresolved_allowed_resources": list(self.unresolved_allowed_resources),
            "operation_paths": list(self.operation_paths),
            "source_resource_types": list(self.source_resource_types),
        }


@dataclass(frozen=True, slots=True)
class AzureResourceDefinitionEvidence:
    """One schema explicitly marked as an Azure resource by the official extension."""

    source_document: str
    json_pointer: str
    operation_paths: tuple[str, ...]
    source_resource_types: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_document": self.source_document,
            "json_pointer": self.json_pointer,
            "operation_paths": list(self.operation_paths),
            "source_resource_types": list(self.source_resource_types),
        }


@dataclass(frozen=True, slots=True)
class AzureProviderRelationshipSchemaSnapshot:
    """Complete normalized relationship evidence from one immutable REST specification tree."""

    source_revision: str
    provider_schema_digest: str
    extension_document_count: int
    arm_id_references: tuple[AzureArmIdReference, ...]
    resource_definitions: tuple[AzureResourceDefinitionEvidence, ...]
    evidence_digest: str

    @classmethod
    def build(
        cls,
        *,
        source_revision: str,
        provider_schema_digest: str,
        extension_document_count: int,
        arm_id_references: Sequence[AzureArmIdReference],
        resource_definitions: Sequence[AzureResourceDefinitionEvidence],
    ) -> AzureProviderRelationshipSchemaSnapshot:
        if not _REVISION_PATTERN.fullmatch(source_revision):
            raise ProviderSchemaError("Azure REST source revision MUST be immutable lowercase hex")
        if not _DIGEST_PATTERN.fullmatch(provider_schema_digest):
            raise ProviderSchemaError(
                "provider schema digest MUST be sha256-prefixed lowercase hex"
            )
        references = tuple(
            sorted(
                arm_id_references,
                key=lambda item: (item.source_document, item.json_pointer),
            )
        )
        definitions = tuple(
            sorted(
                resource_definitions,
                key=lambda item: (item.source_document, item.json_pointer),
            )
        )
        if not references:
            raise ProviderSchemaError("Azure REST relationship snapshot has no ARM ID references")
        material = {
            "schema_version": "1.0.0",
            "provider": "azure",
            "source_kind": "azure-rest-api-specs",
            "source_revision": source_revision,
            "provider_schema_digest": provider_schema_digest,
            "extension_document_count": extension_document_count,
            "arm_id_references": [item.to_mapping() for item in references],
            "resource_definitions": [item.to_mapping() for item in definitions],
        }
        digest = "sha256:" + hashlib.sha256(_canonical_json(material)).hexdigest()
        return cls(
            source_revision=source_revision,
            provider_schema_digest=provider_schema_digest,
            extension_document_count=extension_document_count,
            arm_id_references=references,
            resource_definitions=definitions,
            evidence_digest=digest,
        )

    @property
    def exact_reference_count(self) -> int:
        return sum(item.resolved for item in self.arm_id_references)

    @property
    def unresolved_reference_count(self) -> int:
        return len(self.arm_id_references) - self.exact_reference_count

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "provider": "azure",
            "source_kind": "azure-rest-api-specs",
            "source_revision": self.source_revision,
            "provider_schema_digest": self.provider_schema_digest,
            "evidence_digest": self.evidence_digest,
            "extension_document_count": self.extension_document_count,
            "arm_id_reference_count": len(self.arm_id_references),
            "exact_reference_count": self.exact_reference_count,
            "unresolved_reference_count": self.unresolved_reference_count,
            "resource_definition_count": len(self.resource_definitions),
            "arm_id_references": [item.to_mapping() for item in self.arm_id_references],
            "resource_definitions": [item.to_mapping() for item in self.resource_definitions],
            "grants_authority": False,
        }


class AzureRestApiRelationshipSchemaParser:
    """Scan every extension-bearing JSON document in one pinned specification tree."""

    def __init__(self, *, min_document_count: int = 1, max_document_count: int = 10_000) -> None:
        if min_document_count < 1 or max_document_count < min_document_count:
            raise ValueError("Azure REST extension document bounds are invalid")
        self._min_document_count = min_document_count
        self._max_document_count = max_document_count

    def parse(
        self,
        *,
        tree_root: Path,
        source_revision: str,
        provider_schema_digest: str,
    ) -> AzureProviderRelationshipSchemaSnapshot:
        if not _REVISION_PATTERN.fullmatch(source_revision):
            raise ProviderSchemaError("Azure REST source revision MUST be immutable lowercase hex")
        root = tree_root.resolve()
        specification = root / "specification"
        if not specification.is_dir():
            raise ProviderSchemaError("Azure REST specification tree is unavailable")
        candidates = _extension_documents(specification)
        if not self._min_document_count <= len(candidates) <= self._max_document_count:
            raise ProviderSchemaError(
                "Azure REST extension document count is outside complete-corpus bounds"
            )

        references: list[AzureArmIdReference] = []
        definitions: list[AzureResourceDefinitionEvidence] = []
        for document in candidates:
            relative = document.relative_to(root).as_posix()
            raw = _load_document(document)
            operations = _operation_definition_index(raw)
            for pointer, node in _walk(raw):
                operation_paths = _operation_paths(pointer, operations)
                source_types = tuple(
                    sorted(
                        {
                            resource_type
                            for path in operation_paths
                            for resource_type in _resource_types_from_path(path)
                        }
                    )
                )
                if node.get("format") == "arm-id":
                    exact_targets, unresolved_targets = _allowed_resource_types(
                        node,
                        pointer=pointer,
                    )
                    references.append(
                        AzureArmIdReference(
                            source_document=relative,
                            json_pointer=pointer,
                            allowed_resource_types=exact_targets,
                            unresolved_allowed_resources=unresolved_targets,
                            operation_paths=operation_paths,
                            source_resource_types=source_types,
                        )
                    )
                if node.get("x-ms-azure-resource") is True:
                    definitions.append(
                        AzureResourceDefinitionEvidence(
                            source_document=relative,
                            json_pointer=pointer,
                            operation_paths=operation_paths,
                            source_resource_types=source_types,
                        )
                    )
        return AzureProviderRelationshipSchemaSnapshot.build(
            source_revision=source_revision,
            provider_schema_digest=provider_schema_digest,
            extension_document_count=len(candidates),
            arm_id_references=references,
            resource_definitions=definitions,
        )


class LocalAzureRestApiRelationshipSchemaSource:
    """Read one mounted primary, mirror, or signed-offline REST specification tree."""

    def __init__(
        self,
        *,
        tree_root: Path,
        source_revision: str,
        provider_schema_digest: str,
        parser: AzureRestApiRelationshipSchemaParser,
    ) -> None:
        self._tree_root = tree_root
        self._source_revision = source_revision
        self._provider_schema_digest = provider_schema_digest
        self._parser = parser

    async def collect(self) -> AzureProviderRelationshipSchemaSnapshot:
        return await asyncio.to_thread(
            self._parser.parse,
            tree_root=self._tree_root,
            source_revision=self._source_revision,
            provider_schema_digest=self._provider_schema_digest,
        )


class GitAzureRestApiRelationshipSchemaSource:
    """Fetch one exact REST specification revision before extracting relationship evidence."""

    def __init__(
        self,
        *,
        repo_url: str,
        revision_ref: str,
        provider_schema_digest: str,
        parser: AzureRestApiRelationshipSchemaParser,
        timeout_seconds: float = 300.0,
        revision_resolver: Callable[[str, str, float], str] | None = None,
        tree_fetcher: Callable[[str, str, Path, float], Path] | None = None,
    ) -> None:
        _validate_git_source(repo_url, revision_ref, timeout_seconds=timeout_seconds)
        if not _DIGEST_PATTERN.fullmatch(provider_schema_digest):
            raise ValueError("provider schema digest MUST be sha256-prefixed lowercase hex")
        self._repo_url = repo_url
        self._revision_ref = revision_ref
        self._provider_schema_digest = provider_schema_digest
        self._parser = parser
        self._timeout_seconds = timeout_seconds
        self._revision_resolver = revision_resolver or _resolve_git_revision
        self._tree_fetcher = tree_fetcher or _fetch_git_tree

    async def collect(self) -> AzureProviderRelationshipSchemaSnapshot:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> AzureProviderRelationshipSchemaSnapshot:
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
            raise ProviderSchemaError("resolved Azure REST revision is not immutable lowercase hex")
        with tempfile.TemporaryDirectory(prefix="fdai-provider-relationships-") as temporary:
            tree = self._tree_fetcher(
                self._repo_url,
                revision,
                Path(temporary),
                self._timeout_seconds,
            )
            return self._parser.parse(
                tree_root=tree,
                source_revision=revision,
                provider_schema_digest=self._provider_schema_digest,
            )


def _extension_documents(specification: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for path in specification.rglob("*.json"):
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ProviderSchemaError("Azure REST JSON document is unreadable") from exc
        if b'"format"' in content and b'"arm-id"' in content or b"x-ms-azure-resource" in content:
            candidates.append(path)
    return tuple(sorted(candidates))


def _load_document(path: Path) -> Mapping[str, object]:
    try:
        content = path.read_bytes()
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        raw = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderSchemaError("Azure REST extension document is invalid JSON") from exc
    if not isinstance(raw, Mapping):
        raise ProviderSchemaError("Azure REST extension document root MUST be an object")
    return raw


def _walk(value: object, pointer: str = "") -> Iterator[tuple[str, Mapping[str, object]]]:
    if isinstance(value, Mapping):
        yield pointer or "/", value
        for key, child in value.items():
            if isinstance(key, str):
                yield from _walk(child, f"{pointer}/{_escape_pointer(key)}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            yield from _walk(child, f"{pointer}/{index}")


def _allowed_resource_types(
    node: Mapping[str, object],
    *,
    pointer: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    details = node.get("x-ms-arm-id-details")
    if details is None:
        return (), ()
    if not isinstance(details, Mapping):
        raise ProviderSchemaError(f"Azure REST ARM ID details are invalid at {pointer}")
    allowed = details.get("allowedResources")
    if allowed is None:
        return (), ()
    if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)):
        return (), (_canonical_json_text(allowed),)
    resource_types: list[str] = []
    unresolved_types: list[str] = []
    for item in allowed:
        if not isinstance(item, Mapping) or not isinstance(item.get("type"), str):
            unresolved_types.append(_canonical_json_text(item))
            continue
        resource_type = item["type"]
        if _RESOURCE_TYPE_PATTERN.fullmatch(resource_type):
            resource_types.append(resource_type.casefold())
        else:
            unresolved_types.append(resource_type)
    normalized = tuple(sorted(set(resource_types)))
    unresolved = tuple(sorted(set(unresolved_types)))
    if len(normalized) != len(resource_types) or len(unresolved) != len(unresolved_types):
        raise ProviderSchemaError(f"Azure REST allowed resource types repeat at {pointer}")
    return normalized, unresolved


def _operation_definition_index(raw: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    paths = raw.get("paths")
    if not isinstance(paths, Mapping):
        return {}
    definitions = _definitions(raw)
    indexed: dict[str, set[str]] = {}
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, Mapping):
                continue
            for definition in _reachable_definitions(operation, definitions):
                indexed.setdefault(definition, set()).add(path)
    return {key: tuple(sorted(values)) for key, values in indexed.items()}


def _definitions(raw: Mapping[str, object]) -> dict[str, object]:
    definitions = raw.get("definitions")
    if isinstance(definitions, Mapping):
        return {
            f"/definitions/{_escape_pointer(str(key))}": value for key, value in definitions.items()
        }
    components = raw.get("components")
    if isinstance(components, Mapping) and isinstance(components.get("schemas"), Mapping):
        schemas = components["schemas"]
        return {
            f"/components/schemas/{_escape_pointer(str(key))}": value
            for key, value in schemas.items()
        }
    return {}


def _reachable_definitions(
    operation: Mapping[str, object],
    definitions: Mapping[str, object],
) -> set[str]:
    queue = deque(_local_definition_refs(operation))
    reached: set[str] = set()
    while queue:
        pointer = queue.popleft()
        if pointer in reached or pointer not in definitions:
            continue
        reached.add(pointer)
        queue.extend(_local_definition_refs(definitions[pointer]))
    return reached


def _local_definition_refs(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str) and (
            reference.startswith("#/definitions/") or reference.startswith("#/components/schemas/")
        ):
            yield reference[1:]
        for child in value.values():
            yield from _local_definition_refs(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _local_definition_refs(child)


def _operation_paths(pointer: str, index: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    for definition, paths in index.items():
        if pointer == definition or pointer.startswith(f"{definition}/"):
            return paths
    if pointer.startswith("/paths/"):
        encoded_path = pointer.split("/", maxsplit=3)[2]
        return (_unescape_pointer(encoded_path),)
    return ()


def _resource_types_from_path(path: str) -> tuple[str, ...]:
    segments = [segment for segment in path.split("/") if segment]
    resource_types: list[str] = []
    for provider_index, segment in enumerate(segments):
        if segment.casefold() != "providers" or provider_index + 1 >= len(segments):
            continue
        namespace = segments[provider_index + 1]
        type_segments: list[str] = []
        cursor = provider_index + 2
        while cursor + 1 < len(segments):
            resource_type, resource_name = segments[cursor : cursor + 2]
            if not (resource_name.startswith("{") and resource_name.endswith("}")):
                break
            type_segments.append(resource_type)
            resource_types.append(f"{namespace}/{'/'.join(type_segments)}".casefold())
            cursor += 2
    return tuple(resource_types)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _unescape_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _canonical_json_text(value: object) -> str:
    try:
        return _canonical_json(value).decode("ascii")
    except (TypeError, ValueError) as exc:
        raise ProviderSchemaError("Azure REST unresolved allowed resource is not JSON") from exc


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
        raise ValueError("provider relationship Git source MUST be credential-free HTTPS")
    if not revision_ref.strip() or not revision_ref.isascii():
        raise ValueError("provider relationship Git revision ref MUST be non-empty ASCII")
    if timeout_seconds <= 0:
        raise ValueError("provider relationship Git timeout MUST be positive")


def _resolve_git_revision(repo_url: str, revision_ref: str, timeout_seconds: float) -> str:
    git_binary = shutil.which("git")
    if git_binary is None:
        raise ProviderSchemaError("provider relationship Git executable is unavailable")
    process = subprocess.run(  # noqa: S603 - fixed binary and argv; no shell.
        [git_binary, "ls-remote", "--exit-code", repo_url, revision_ref],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if process.returncode != 0:
        raise ProviderSchemaError("provider relationship Git revision lookup failed")
    revisions = {line.split(maxsplit=1)[0] for line in process.stdout.splitlines() if line.strip()}
    if len(revisions) != 1:
        raise ProviderSchemaError("provider relationship Git revision lookup is ambiguous")
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
    "AzureArmIdReference",
    "AzureProviderRelationshipSchemaSnapshot",
    "AzureResourceDefinitionEvidence",
    "AzureRestApiRelationshipSchemaParser",
    "GitAzureRestApiRelationshipSchemaSource",
    "LocalAzureRestApiRelationshipSchemaSource",
]
