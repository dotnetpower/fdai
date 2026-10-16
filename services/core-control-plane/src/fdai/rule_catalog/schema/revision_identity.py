"""Immutable identities for complete executable Rule revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai.shared.contracts.models import CheckLogicKind, ContractBase, Rule

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_PACKAGE_PATTERN = re.compile(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)\s*$")
_DATA_REFERENCE_PATTERN = re.compile(r"\bdata\.([A-Za-z0-9_.]+)")
_BARE_DATA_REFERENCE_PATTERN = re.compile(r"\bdata\b")
_MAX_ARTIFACT_BYTES = 1_000_000
RULE_POLICY_NORMALIZATION_VERSION = "1.0.0"


class RulePolicyArtifact(ContractBase):
    """One exact executable policy module or data document."""

    path: Annotated[str, Field(min_length=1, max_length=512)]
    kind: Literal["rego", "data", "expression"]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _path_is_canonical(self) -> RulePolicyArtifact:
        if self.path != self.path.strip() or self.path.startswith("/"):
            raise ValueError("Rule policy artifact path MUST be exact and relative")
        parts = Path(self.path).parts
        if not parts or ".." in parts or "." in parts:
            raise ValueError("Rule policy artifact path MUST NOT traverse")
        return self


class RuleRevisionIdentity(ContractBase):
    """Permanent identity for one Rule definition and executable policy bundle."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    rule_version: Annotated[str, Field(min_length=1, max_length=64)]
    definition_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    policy_identity_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    opa_version: Annotated[str, Field(min_length=1, max_length=64)]
    opa_toolchain_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    normalization_version: Annotated[str, Field(min_length=1, max_length=64)]
    normalization_source_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    artifacts: Annotated[tuple[RulePolicyArtifact, ...], Field(min_length=1, max_length=1_000)]
    revision_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _identity_is_canonical(self) -> RuleRevisionIdentity:
        for value in (
            self.rule_id,
            self.rule_version,
            self.opa_version,
            self.normalization_version,
        ):
            if value != value.strip():
                raise ValueError("Rule revision identity text MUST be exact")
        artifact_paths = tuple(artifact.path for artifact in self.artifacts)
        if artifact_paths != tuple(sorted(artifact_paths)) or len(set(artifact_paths)) != len(
            artifact_paths
        ):
            raise ValueError("Rule revision policy artifacts MUST be unique and sorted")
        expected_policy = policy_identity_digest(
            self.artifacts,
            opa_version=self.opa_version,
            opa_toolchain_digest=self.opa_toolchain_digest,
            normalization_version=self.normalization_version,
            normalization_source_digest=self.normalization_source_digest,
        )
        if self.policy_identity_digest != expected_policy:
            raise ValueError("Rule policy identity digest does not match artifacts")
        expected_revision = rule_revision_digest(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            definition_digest=self.definition_digest,
            policy_identity_digest=self.policy_identity_digest,
        )
        if self.revision_digest != expected_revision:
            raise ValueError("Rule revision digest does not match identity")
        return self

    @property
    def key(self) -> tuple[str, str]:
        """Return the collision-free revision key."""

        return (self.rule_id, self.rule_version)


class RuleRevisionRegistry(ContractBase):
    """Retained immutable Rule revisions available to one release."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    revisions: Annotated[tuple[RuleRevisionIdentity, ...], Field(min_length=1, max_length=50_000)]

    @model_validator(mode="after")
    def _revisions_are_unique_and_sorted(self) -> RuleRevisionRegistry:
        keys = tuple(revision.key for revision in self.revisions)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule revision registry entries MUST be unique and sorted")
        return self

    def by_key(self) -> dict[tuple[str, str], RuleRevisionIdentity]:
        """Return exact tuple-keyed entries without string concatenation."""

        return {revision.key: revision for revision in self.revisions}


def build_rule_revision_identity(
    rule: Rule,
    artifacts: Iterable[RulePolicyArtifact],
    *,
    opa_version: str,
    opa_toolchain_digest: str,
    normalization_source_digest: str,
    normalization_version: str = RULE_POLICY_NORMALIZATION_VERSION,
) -> RuleRevisionIdentity:
    """Build one immutable revision identity from a validated Rule and bundle."""

    canonical_artifacts = tuple(sorted(artifacts, key=lambda artifact: artifact.path))
    definition_digest = rule_definition_digest(rule)
    policy_digest = policy_identity_digest(
        canonical_artifacts,
        opa_version=opa_version,
        opa_toolchain_digest=opa_toolchain_digest,
        normalization_version=normalization_version,
        normalization_source_digest=normalization_source_digest,
    )
    revision_digest = rule_revision_digest(
        rule_id=rule.id,
        rule_version=str(rule.version),
        definition_digest=definition_digest,
        policy_identity_digest=policy_digest,
    )
    return RuleRevisionIdentity(
        rule_id=rule.id,
        rule_version=str(rule.version),
        definition_digest=definition_digest,
        policy_identity_digest=policy_digest,
        opa_version=opa_version,
        opa_toolchain_digest=opa_toolchain_digest,
        normalization_version=normalization_version,
        normalization_source_digest=normalization_source_digest,
        artifacts=canonical_artifacts,
        revision_digest=revision_digest,
    )


def repository_policy_artifacts(
    rule: Rule,
    *,
    repository_root: Path,
) -> tuple[RulePolicyArtifact, ...]:
    """Resolve one Rule's complete current executable bundle from repository files."""

    reference = rule.check_logic.reference
    if rule.check_logic.kind is CheckLogicKind.EXPRESSION:
        return (
            RulePolicyArtifact(
                path=f"expression/{rule.id}",
                kind="expression",
                content_digest=_digest_bytes(reference.encode("utf-8")),
            ),
        )
    if not reference.startswith("policies/"):
        raise ValueError("Rego Rule policy reference MUST start with policies/")
    policies_root = _resolved_directory(repository_root / "policies", repository_root)
    entrypoint = _resolved_file(repository_root / reference, repository_root)
    package_index = _rego_package_index(policies_root, repository_root)
    pending = deque([entrypoint])
    visited: set[Path] = set()
    artifacts: list[RulePolicyArtifact] = []
    while pending:
        path = pending.popleft()
        if path in visited:
            continue
        visited.add(path)
        content = _bounded_bytes(path)
        artifacts.append(
            RulePolicyArtifact(
                path=path.relative_to(repository_root).as_posix(),
                kind="rego" if path.suffix == ".rego" else "data",
                content_digest=_digest_bytes(content),
            )
        )
        if path.suffix != ".rego":
            continue
        text = content.decode("utf-8")
        reference_source = _rego_reference_source(text)
        static_references = tuple(_DATA_REFERENCE_PATTERN.findall(reference_source))
        without_static_references = _DATA_REFERENCE_PATTERN.sub("", reference_source)
        if _BARE_DATA_REFERENCE_PATTERN.search(without_static_references):
            raise ValueError(
                f"dynamic Rego data reference cannot produce a complete closure: {path.name}"
            )
        own_package = _package(text, path)
        for reference_path in sorted(set(static_references)):
            dependencies = _resolve_data_reference(
                reference_path,
                own_package=own_package,
                package_index=package_index,
                policies_root=policies_root,
                repository_root=repository_root,
            )
            pending.extend(dependency for dependency in dependencies if dependency not in visited)
    return tuple(sorted(artifacts, key=lambda artifact: artifact.path))


def _rego_reference_source(text: str) -> str:
    masked: list[str] = []
    state = "code"
    escaped = False
    for character in text:
        if state == "comment":
            if character == "\n":
                masked.append(character)
                state = "code"
            else:
                masked.append(" ")
            continue
        if state == "quoted":
            masked.append("\n" if character == "\n" else " ")
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                state = "code"
            continue
        if state == "raw":
            masked.append("\n" if character == "\n" else " ")
            if character == "`":
                state = "code"
            continue
        if character == "#":
            masked.append(" ")
            state = "comment"
        elif character == '"':
            masked.append(" ")
            state = "quoted"
        elif character == "`":
            masked.append(" ")
            state = "raw"
        else:
            masked.append(character)
    if state in {"quoted", "raw"}:
        raise ValueError("Rego policy contains an unterminated string")
    return "".join(masked)


def rule_definition_digest(rule: Rule) -> str:
    """Digest the complete normalized Rule definition, including provenance."""

    return _canonical_digest(rule.model_dump(mode="json", exclude_none=True))


def policy_identity_digest(
    artifacts: Iterable[RulePolicyArtifact],
    *,
    opa_version: str,
    opa_toolchain_digest: str,
    normalization_version: str,
    normalization_source_digest: str,
) -> str:
    """Digest the executable artifact closure and its exact policy toolchain."""

    canonical = tuple(sorted(artifacts, key=lambda artifact: artifact.path))
    if not canonical:
        raise ValueError("Rule policy identity requires at least one artifact")
    for digest, label in (
        (opa_toolchain_digest, "OPA toolchain"),
        (normalization_source_digest, "normalization source"),
    ):
        if re.fullmatch(_DIGEST_PATTERN, digest) is None:
            raise ValueError(f"{label} digest MUST be lowercase SHA-256")
    return _canonical_digest(
        {
            "opa_version": _exact_version(opa_version, "OPA"),
            "opa_toolchain_digest": opa_toolchain_digest,
            "normalization_version": _exact_version(normalization_version, "normalization"),
            "normalization_source_digest": normalization_source_digest,
            "artifacts": [artifact.model_dump(mode="json") for artifact in canonical],
        }
    )


def rule_revision_digest(
    *,
    rule_id: str,
    rule_version: str,
    definition_digest: str,
    policy_identity_digest: str,
) -> str:
    """Digest the permanent tuple identity without ambiguous string joining."""

    return _canonical_digest(
        {
            "rule_id": rule_id,
            "rule_version": rule_version,
            "definition_digest": definition_digest,
            "policy_identity_digest": policy_identity_digest,
        }
    )


def _rego_package_index(
    policies_root: Path,
    repository_root: Path,
) -> Mapping[str, Path]:
    packages: dict[str, Path] = {}
    for path in sorted(policies_root.rglob("*.rego")):
        resolved = _resolved_file(path, repository_root)
        package_name = _package(_bounded_bytes(resolved).decode("utf-8"), resolved)
        if package_name in packages:
            raise ValueError(f"duplicate Rego package in policy bundle: {package_name}")
        packages[package_name] = resolved
    return packages


def _resolve_data_reference(
    reference: str,
    *,
    own_package: str,
    package_index: Mapping[str, Path],
    policies_root: Path,
    repository_root: Path,
) -> tuple[Path, ...]:
    ancestor_matches = [
        (package_name, path)
        for package_name, path in package_index.items()
        if reference == package_name or reference.startswith(f"{package_name}.")
    ]
    subtree_matches = [
        path
        for package_name, path in package_index.items()
        if package_name.startswith(f"{reference}.")
    ]
    resolved: set[Path] = set(subtree_matches)
    if ancestor_matches:
        longest = max(len(package_name) for package_name, _ in ancestor_matches)
        matches = [path for package_name, path in ancestor_matches if len(package_name) == longest]
        if len(set(matches)) != 1:
            raise ValueError(f"ambiguous Rego data dependency: data.{reference}")
        resolved.add(matches[0])
    own_module = package_index.get(own_package)
    if own_module is not None:
        resolved.discard(own_module)
    if resolved:
        return tuple(sorted(resolved))
    if reference == own_package or reference.startswith(f"{own_package}."):
        return ()
    relative = Path(*reference.split("."))
    for suffix in (".json", ".yaml", ".yml"):
        candidate = policies_root / relative.with_suffix(suffix)
        if candidate.is_file():
            return (_resolved_file(candidate, repository_root),)
    raise ValueError(f"unresolved Rego data dependency: data.{reference}")


def _package(text: str, path: Path) -> str:
    match = _PACKAGE_PATTERN.search(text)
    if match is None:
        raise ValueError(f"Rego policy has no package declaration: {path.name}")
    return match.group(1)


def _resolved_directory(path: Path, repository_root: Path) -> Path:
    resolved = path.resolve(strict=True)
    root = repository_root.resolve(strict=True)
    if not resolved.is_dir() or not resolved.is_relative_to(root):
        raise ValueError("Rule policy root MUST stay inside the repository")
    return resolved


def _resolved_file(path: Path, repository_root: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Rule policy artifacts MUST NOT be symlinks")
    resolved = path.resolve(strict=True)
    root = repository_root.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("Rule policy artifact MUST stay inside the repository")
    return resolved


def _bounded_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    if not content or len(content) > _MAX_ARTIFACT_BYTES:
        raise ValueError(f"Rule policy artifact size is invalid: {path.name}")
    return content


def _exact_version(value: str, label: str) -> str:
    if not value or value != value.strip() or len(value) > 64:
        raise ValueError(f"{label} version MUST be exact bounded text")
    return value


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = [
    "RULE_POLICY_NORMALIZATION_VERSION",
    "RulePolicyArtifact",
    "RuleRevisionIdentity",
    "RuleRevisionRegistry",
    "build_rule_revision_identity",
    "policy_identity_digest",
    "repository_policy_artifacts",
    "rule_definition_digest",
    "rule_revision_digest",
]
