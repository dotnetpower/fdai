#!/usr/bin/env python3
"""Validate the immutable Rule revision registry or append new revisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/core-control-plane/src"))
sys.path.insert(0, str(ROOT / "packages/service-contracts/src"))

from fdai.rule_catalog.schema.revision_identity import (  # noqa: E402
    RulePolicyArtifact,
    RuleRevisionIdentity,
    RuleRevisionRegistry,
    build_rule_revision_identity,
    policy_identity_digest,
    repository_policy_artifacts,
    rule_definition_digest,
)
from fdai.shared.contracts.models import Rule  # noqa: E402

REGISTRY = ROOT / "rule-catalog/rule-revision-identities.json"
ARTIFACT_ROOT = ROOT / "rule-catalog/revisions"
CATALOG = ROOT / "rule-catalog/catalog"
_OPA_VERSION = re.compile(r"^ARG OPA_VERSION=v?([^\s]+)$", re.MULTILINE)
_PYTHON_BUILDER = re.compile(
    r"^FROM\s+(.+python@sha256:[a-f0-9]{64})\s+AS\s+builder$", re.MULTILINE
)
_REGISTRY_PATH = "rule-catalog/rule-revision-identities.json"
_OPA_GO_VERSION = re.compile(r"^(ARG OPA_GO_VERSION=)(go\d+\.\d+)\.\d+$")
_OPA_GO_BUILDER = re.compile(r"^(FROM\s+\S*golang@)sha256:[0-9a-f]{64}(\s+AS\s+opa-builder)$")
# A Go patch release does not change how Rego evaluates, so the identity hashes the Go pin of a
# minor series as the baseline that the retained revisions recorded. A Go minor series that has no
# entry here is hashed as written, so adopting it changes every Rule identity and requires a Rule
# version bump. Add an entry only together with that bump, using the pin that was actually built.
_GO_IDENTITY_BASELINES = {
    "go1.27": (
        "go1.27.2",
        "sha256:85dc1069ac644ea3c527b177303a406eb3358192816cd7f9e5848eb658851673",
    ),
}
_NORMALIZATION_SOURCES = (
    "services/core-control-plane/src/fdai/rule_catalog/schema/revision_identity.py",
    "services/core-control-plane/src/fdai/shared/contracts/models/rule.py",
    "services/core-control-plane/src/fdai/shared/contracts/models/_base.py",
    "services/core-control-plane/src/fdai/shared/contracts/models/enums.py",
)
_NORMALIZATION_PACKAGES = frozenset({"pydantic", "pydantic-core", "pyyaml"})


def current_revisions(root: Path = ROOT) -> tuple[RuleRevisionIdentity, ...]:
    """Build the exact current revision set from normalized Rules and policy artifacts."""

    return tuple(
        material["identity"]
        for material in sorted(
            _current_materials(root).values(),
            key=lambda material: material["identity"].key,
        )
    )


def _current_materials(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    opa_version, opa_toolchain_digest = _opa_toolchain(root)
    normalization_source_digest = _normalization_source_digest(root)
    materials: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((root / "rule-catalog/catalog").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            rule = Rule.model_validate(raw)
            artifacts = repository_policy_artifacts(rule, repository_root=root)
            identity = build_rule_revision_identity(
                rule,
                artifacts,
                opa_version=opa_version,
                opa_toolchain_digest=opa_toolchain_digest,
                normalization_source_digest=normalization_source_digest,
            )
            if identity.key in materials:
                raise ValueError("duplicate Rule revision identity")
            materials[identity.key] = {
                "identity": identity,
                "definition": rule.model_dump(mode="json", exclude_none=True),
                "artifact_contents": _artifact_contents(rule, artifacts, root=root),
            }
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"{path.relative_to(root)}: {exc}") from exc
    return materials


def violations(
    retained: tuple[RuleRevisionIdentity, ...],
    current: tuple[RuleRevisionIdentity, ...],
    *,
    baseline: tuple[RuleRevisionIdentity, ...] = (),
    artifact_root: Path = ARTIFACT_ROOT,
) -> list[str]:
    """Return historical rewrites, in-place changes, and missing artifacts."""

    retained_by_key = {revision.key: revision for revision in retained}
    problems: list[str] = []
    for revision in baseline:
        preserved = retained_by_key.get(revision.key)
        if preserved is None:
            problems.append(
                f"{revision.rule_id}@{revision.rule_version}: retained revision was removed"
            )
        elif preserved != revision:
            problems.append(
                f"{revision.rule_id}@{revision.rule_version}: retained revision was rewritten"
            )
    for revision in current:
        previous = retained_by_key.get(revision.key)
        if previous is None:
            problems.append(
                f"{revision.rule_id}@{revision.rule_version}: new Rule revision is not registered"
            )
        elif previous != revision:
            problems.append(
                f"{revision.rule_id}@{revision.rule_version}: immutable Rule revision changed"
            )
    for revision in retained:
        problems.extend(_artifact_violations(revision, artifact_root=artifact_root))
    return problems


def _load_registry(path: Path = REGISTRY) -> tuple[RuleRevisionIdentity, ...]:
    if not path.is_file():
        return ()
    return RuleRevisionRegistry.model_validate_json(path.read_text(encoding="utf-8")).revisions


def _write_registry(
    retained: tuple[RuleRevisionIdentity, ...],
    current_materials: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    path: Path = REGISTRY,
    artifact_root: Path = ARTIFACT_ROOT,
) -> tuple[RuleRevisionIdentity, ...]:
    retained_by_key = {revision.key: revision for revision in retained}
    for material in current_materials.values():
        revision = material["identity"]
        if not isinstance(revision, RuleRevisionIdentity):
            raise SystemExit("current Rule revision material has an invalid identity")
        previous = retained_by_key.get(revision.key)
        if previous is not None and previous != revision:
            raise SystemExit(
                f"{revision.rule_id}@{revision.rule_version}: "
                "refusing to rewrite immutable revision"
            )
        retained_by_key.setdefault(revision.key, revision)
        _write_artifact(
            revision,
            definition=material["definition"],
            artifact_contents=material["artifact_contents"],
            artifact_root=artifact_root,
        )
    registry = RuleRevisionRegistry(
        revisions=tuple(sorted(retained_by_key.values(), key=lambda revision: revision.key))
    )
    path.write_text(
        json.dumps(registry.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return registry.revisions


def _opa_toolchain(root: Path) -> tuple[str, str]:
    dockerfile = root / "services/core-control-plane/docker/Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    match = _OPA_VERSION.search(text)
    if match is None:
        raise SystemExit("Core Dockerfile does not pin OPA_VERSION")
    lines = text.splitlines()
    stage: list[str] = []
    found_builder = False
    for line in lines:
        if line.startswith("FROM "):
            if found_builder:
                break
            found_builder = line.rstrip().endswith(" AS opa-builder")
        if found_builder:
            stage.append(line.rstrip())
    if not stage:
        raise SystemExit("Core Dockerfile does not define the OPA builder stage")
    stage = _normalize_go_patch_pin(stage)
    return match.group(1), _digest_bytes(("\n".join(stage) + "\n").encode("utf-8"))


def _normalize_go_patch_pin(stage: list[str]) -> list[str]:
    """Map a Go patch pin to its minor series baseline so patch releases keep the identity."""

    series = next(
        (match.group(2) for line in stage if (match := _OPA_GO_VERSION.match(line))),
        None,
    )
    baseline = _GO_IDENTITY_BASELINES.get(series) if series is not None else None
    if baseline is None:
        return stage
    version, digest = baseline
    normalized: list[str] = []
    for line in stage:
        if _OPA_GO_VERSION.match(line):
            line = f"ARG OPA_GO_VERSION={version}"
        elif (builder := _OPA_GO_BUILDER.match(line)) is not None:
            line = f"{builder.group(1)}{digest}{builder.group(2)}"
        normalized.append(line)
    return normalized


def _normalization_source_digest(root: Path) -> str:
    dockerfile = (root / "services/core-control-plane/docker/Dockerfile").read_text(
        encoding="utf-8"
    )
    python_builder = _PYTHON_BUILDER.search(dockerfile)
    if python_builder is None:
        raise SystemExit("Core Dockerfile does not pin the Python builder image")
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise SystemExit("uv.lock package inventory is invalid")
    versions = {
        str(package.get("name")): str(package.get("version"))
        for package in packages
        if isinstance(package, Mapping) and package.get("name") in _NORMALIZATION_PACKAGES
    }
    if set(versions) != _NORMALIZATION_PACKAGES:
        raise SystemExit("uv.lock does not pin the complete Rule normalization toolchain")
    sources = {
        relative: _digest_bytes((root / relative).read_bytes())
        for relative in _NORMALIZATION_SOURCES
    }
    return _digest_bytes(
        json.dumps(
            {
                "python_builder": python_builder.group(1),
                "packages": dict(sorted(versions.items())),
                "sources": sources,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _artifact_contents(
    rule: Rule,
    artifacts: tuple[RulePolicyArtifact, ...],
    *,
    root: Path,
) -> dict[str, str]:
    contents: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.kind == "expression":
            contents[artifact.path] = rule.check_logic.reference
        else:
            contents[artifact.path] = (root / artifact.path).read_text(encoding="utf-8")
    return contents


def _artifact_path(revision: RuleRevisionIdentity, *, artifact_root: Path) -> Path:
    return artifact_root / f"{revision.revision_digest.removeprefix('sha256:')}.json"


def _write_artifact(
    revision: RuleRevisionIdentity,
    *,
    definition: object,
    artifact_contents: object,
    artifact_root: Path,
) -> None:
    if not isinstance(artifact_contents, Mapping):
        raise SystemExit("Rule revision artifact contents are invalid")
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = _artifact_path(revision, artifact_root=artifact_root)
    value = {
        "schema_version": "1.0.0",
        "revision_identity": revision.model_dump(mode="json"),
        "definition": definition,
        "policy_artifacts": [
            {
                **artifact.model_dump(mode="json"),
                "content": artifact_contents[artifact.path],
            }
            for artifact in revision.artifacts
        ],
    }
    rendered = json.dumps(value, indent=2, ensure_ascii=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise SystemExit(f"refusing to rewrite retained Rule revision artifact: {path.name}")
    path.write_text(rendered, encoding="utf-8")


def _artifact_violations(
    revision: RuleRevisionIdentity,
    *,
    artifact_root: Path,
) -> list[str]:
    label = f"{revision.rule_id}@{revision.rule_version}"
    path = _artifact_path(revision, artifact_root=artifact_root)
    if not path.is_file():
        return [f"{label}: retained revision artifact is missing"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, Mapping)
            or raw.get("schema_version") != "1.0.0"
            or RuleRevisionIdentity.model_validate(raw.get("revision_identity")) != revision
        ):
            raise ValueError("identity mismatch")
        rule = Rule.model_validate(raw.get("definition"))
        if rule_definition_digest(rule) != revision.definition_digest:
            raise ValueError("definition digest mismatch")
        policy_rows = raw.get("policy_artifacts")
        if not isinstance(policy_rows, list):
            raise ValueError("policy artifacts are invalid")
        artifacts: list[RulePolicyArtifact] = []
        for row in policy_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("content"), str):
                raise ValueError("policy artifact content is invalid")
            artifact = RulePolicyArtifact.model_validate(
                {key: row[key] for key in ("path", "kind", "content_digest")}
            )
            if _digest_bytes(row["content"].encode("utf-8")) != artifact.content_digest:
                raise ValueError("policy artifact digest mismatch")
            artifacts.append(artifact)
        if tuple(artifacts) != revision.artifacts:
            raise ValueError("policy artifact manifest mismatch")
        if (
            policy_identity_digest(
                artifacts,
                opa_version=revision.opa_version,
                opa_toolchain_digest=revision.opa_toolchain_digest,
                normalization_version=revision.normalization_version,
                normalization_source_digest=revision.normalization_source_digest,
            )
            != revision.policy_identity_digest
        ):
            raise ValueError("policy identity mismatch")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"{label}: retained revision artifact is invalid ({exc})"]
    return []


def _baseline_registry(
    base_ref: str,
    *,
    root: Path = ROOT,
) -> tuple[RuleRevisionIdentity, ...]:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        completed = subprocess.run(
            ["git", "show", f"{base_ref}:{_REGISTRY_PATH}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Rule revision baseline is unavailable: {base_ref}") from exc
    if completed.returncode != 0:
        if (
            "does not exist in" in completed.stderr
            or "exists on disk, but not in" in completed.stderr
        ):
            return ()
        raise SystemExit(f"Rule revision baseline read failed: {base_ref}")
    if not completed.stdout:
        raise SystemExit(f"Rule revision baseline registry is empty: {base_ref}")
    try:
        return RuleRevisionRegistry.model_validate_json(completed.stdout).revisions
    except ValueError as exc:
        raise SystemExit(f"Rule revision baseline registry is invalid: {base_ref}") from exc


def _optional_baseline_registry(
    base_ref: str | None,
) -> tuple[RuleRevisionIdentity, ...]:
    if base_ref is None:
        raise SystemExit("--base-ref is required when checking Rule revision history")
    if not base_ref.strip() or base_ref != base_ref.strip():
        raise SystemExit("--base-ref MUST be exact non-empty text")
    return _baseline_registry(base_ref)


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="append new immutable revisions")
    parser.add_argument("--base-ref", help="exact git commit/ref that owns retained history")
    args = parser.parse_args(argv)
    materials = _current_materials(ROOT)
    current = tuple(
        material["identity"]
        for material in sorted(materials.values(), key=lambda item: item["identity"].key)
    )
    retained = _load_registry()
    if args.write:
        retained = _write_registry(retained, materials)
    baseline = _optional_baseline_registry(args.base_ref)
    problems = violations(retained, current, baseline=baseline)
    if problems:
        for problem in problems:
            print(f"rule-revision-identities: {problem}", file=sys.stderr)
        print(
            "rule-revision-identities: bump the Rule version before registering changed content",
            file=sys.stderr,
        )
        return 1
    print(
        "rule-revision-identities: "
        f"OK ({len(current)} current, {len(retained)} retained revision(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
