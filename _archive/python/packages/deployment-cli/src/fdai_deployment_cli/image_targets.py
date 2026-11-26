"""Resolve changed repository paths to independently deployable service images."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ImageTarget:
    target: str
    service: str
    dockerfile: str
    image: str


IMAGE_TARGETS = (
    ImageTarget(
        target="core-control-plane",
        service="core-control-plane",
        dockerfile="services/core-control-plane/docker/Dockerfile",
        image="fdai-core-control-plane",
    ),
    ImageTarget(
        target="cost-governance",
        service="core-control-plane",
        dockerfile="extensions/cost-governance/docker/Dockerfile",
        image="fdai-cost-governance",
    ),
    ImageTarget(
        target="operator-service",
        service="operator-service",
        dockerfile="services/operator-service/docker/Dockerfile",
        image="fdai-operator-service",
    ),
    ImageTarget(
        target="document-ingestion-api",
        service="document-ingestion-api",
        dockerfile="services/document-ingestion-api/docker/Dockerfile",
        image="fdai-document-ingestion-api",
    ),
    ImageTarget(
        target="document-processing-worker",
        service="document-processing-worker",
        dockerfile="services/document-processing-worker/docker/Dockerfile",
        image="fdai-document-processing-worker",
    ),
    ImageTarget(
        target="isolated-executor",
        service="isolated-executor",
        dockerfile="services/isolated-executor/docker/Dockerfile",
        image="fdai-isolated-executor",
    ),
    ImageTarget(
        target="system-knowledge-service",
        service="system-knowledge-service",
        dockerfile="services/system-knowledge-service/docker/Dockerfile",
        image="fdai-system-knowledge-service",
    ),
)

_ALL_TARGET_EXACT_PATHS = {
    ".dockerignore",
    ".github/workflows/container-supply-chain.yml",
    ".trivyignore.yaml",
    "config/service-image-build-override.json",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "scripts/deployment/service/apply_image_build_override.py",
    "scripts/deployment/service/select_changed_images.py",
    "uv.lock",
}
_ALL_TARGET_PREFIXES = (
    "evaluation-sdk/",
    "packages/service-contracts/",
    "service-contracts/",
    "src/",
)
_ALL_TARGET_METADATA_PATHS = {
    "benchmarks/cybergym/pyproject.toml",
    "benchmarks/sregym/pyproject.toml",
    "extensions/code-assurance/pyproject.toml",
    "extensions/cost-governance/pyproject.toml",
    "packages/github-app-auth/pyproject.toml",
    *(f"services/{target.service}/pyproject.toml" for target in IMAGE_TARGETS),
}
_CORE_EXACT_PATHS = {
    "alembic.ini",
    "docs/internals/sregym-absorption-ledger.json",
    "scripts/deployment/local/materialize-authoritative-catalogs.py",
}
_CORE_PREFIXES = (
    "alembic/",
    "config/",
    "policies/",
    "provider-schema-catalog/",
    "rule-catalog/",
    "services/assets/",
    "tests/scenarios/",
)
_COST_GOVERNANCE_PREFIX = "extensions/cost-governance/"
_GITHUB_APP_AUTH_PREFIX = "packages/github-app-auth/"
_RUNTIME_DIAGNOSTICS_PREFIX = "packages/runtime-diagnostics/"
_SOURCE_PACKAGE_PREFIXES = (
    *(f"services/{target.service}/" for target in IMAGE_TARGETS),
    _COST_GOVERNANCE_PREFIX,
    _GITHUB_APP_AUTH_PREFIX,
    _RUNTIME_DIAGNOSTICS_PREFIX,
    "packages/service-contracts/",
    "evaluation-sdk/",
)


def select_requested_images(selection: str) -> tuple[ImageTarget, ...]:
    """Resolve explicit target names without expanding optional image profiles."""
    names = [name.strip() for name in selection.split(",")]
    if names == ["all"]:
        return IMAGE_TARGETS
    by_name = {name: target for target in IMAGE_TARGETS for name in (target.target, target.image)}
    selected: set[str] = set()
    for name in names:
        if name not in by_name:
            raise ValueError("images must name known targets or image names, or only 'all'")
        target = by_name[name]
        if target.target in selected:
            raise ValueError("images must not repeat a target or its image alias")
        selected.add(target.target)
    return tuple(target for target in IMAGE_TARGETS if target.target in selected)


def _is_packaging_input(path: str) -> bool:
    if path == "README.md":
        return False
    for prefix in _SOURCE_PACKAGE_PREFIXES:
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        if relative.startswith("tests/") and not (
            prefix == "services/core-control-plane/" and relative.startswith("tests/scenarios/")
        ):
            return False
        if relative.startswith("docs/"):
            return False
        return not (relative.startswith("src/") and relative.endswith((".py", ".pyi")))
    return not (path.startswith("src/") and path.endswith((".py", ".pyi")))


def select_image_targets(
    changed_paths: Iterable[str], *, packaging_only: bool = False
) -> tuple[ImageTarget, ...]:
    """Select every image whose declared source or packaged asset changed."""
    paths = {path.removeprefix("./") for path in changed_paths if path}
    if packaging_only:
        paths = {path for path in paths if _is_packaging_input(path)}
    if any(
        path in _ALL_TARGET_EXACT_PATHS
        or path in _ALL_TARGET_METADATA_PATHS
        or path.startswith(_ALL_TARGET_PREFIXES)
        for path in paths
    ):
        return IMAGE_TARGETS

    selected: set[str] = set()
    for path in paths:
        if path.startswith(_RUNTIME_DIAGNOSTICS_PREFIX):
            selected.update({"core-control-plane", "cost-governance", "operator-service"})
            continue
        if path.startswith(_GITHUB_APP_AUTH_PREFIX):
            selected.update({"core-control-plane", "cost-governance", "document-ingestion-api"})
            continue
        if path.startswith(_COST_GOVERNANCE_PREFIX):
            selected.add("cost-governance")
            continue
        if path in _CORE_EXACT_PATHS or path.startswith(_CORE_PREFIXES):
            selected.update({"core-control-plane", "cost-governance"})
        if path == "config/agent-stewardship.yaml":
            selected.add("document-ingestion-api")
        if not path.startswith("services/") or path.startswith("services/assets/"):
            continue
        matching = {
            target.target
            for target in IMAGE_TARGETS
            if path.startswith(f"services/{target.service}/")
        }
        if not matching:
            return IMAGE_TARGETS
        selected.update(matching)
    return tuple(target for target in IMAGE_TARGETS if target.target in selected)


def matrix_json(targets: Iterable[ImageTarget]) -> str:
    return json.dumps(
        {"include": [asdict(target) for target in targets]},
        separators=(",", ":"),
    )
