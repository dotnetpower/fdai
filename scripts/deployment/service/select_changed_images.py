"""Select bounded PR packaging checks or explicitly requested candidate images."""

from __future__ import annotations

import argparse
import json
import sys
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
    "rule-catalog/",
    "services/assets/",
    "tests/scenarios/",
)
_CORE_ONLY_PREFIXES = ("provider-schema-catalog/",)
_COST_GOVERNANCE_PREFIX = "extensions/cost-governance/"
_GITHUB_APP_AUTH_PREFIX = "packages/github-app-auth/"
_SOURCE_PACKAGE_PREFIXES = (
    *(f"services/{target.service}/" for target in IMAGE_TARGETS),
    _COST_GOVERNANCE_PREFIX,
    _GITHUB_APP_AUTH_PREFIX,
    "packages/service-contracts/",
    "evaluation-sdk/",
)


def select_requested_images(selection: str) -> tuple[ImageTarget, ...]:
    """Resolve explicit target/image names; reject empty, unknown, or duplicate selections.

    ``all`` is accepted only as the entire selection. Runtime service names map to
    their default image; the optional cost-governance profile is selected separately.
    """
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
    """Exclude known ordinary source/tests, but retain unknown and packaged assets."""
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
    """Select affected images, optionally excluding ordinary source-only PR changes.

    Packaging mode keeps Dockerfiles, dependency metadata, build helpers and
    packaged assets. Unknown service inputs still select all images.
    """
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
        if path.startswith(_CORE_ONLY_PREFIXES):
            selected.add("core-control-plane")
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

        matching_services = {
            target.target
            for target in IMAGE_TARGETS
            if path.startswith(f"services/{target.service}/")
        }
        if not matching_services:
            return IMAGE_TARGETS
        selected.update(matching_services)

    return tuple(target for target in IMAGE_TARGETS if target.target in selected)


def matrix_json(targets: Iterable[ImageTarget]) -> str:
    """Render a compact GitHub Actions matrix payload."""
    return json.dumps(
        {"include": [asdict(target) for target in targets]},
        separators=(",", ":"),
    )


def main() -> int:
    """Emit a matrix only after explicit selections or changed paths are validated."""
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", dest="select_all")
    selection.add_argument("--images", help="Comma-separated target/image names, or explicit all")
    selection.add_argument("--packaging-only", action="store_true")
    parser.add_argument("--nul", action="store_true")
    args = parser.parse_args()

    targets: tuple[ImageTarget, ...]
    if args.select_all:
        targets = IMAGE_TARGETS
    elif args.images is not None:
        try:
            targets = select_requested_images(args.images)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        separator = b"\0" if args.nul else b"\n"
        paths = [
            value.decode("utf-8") for value in sys.stdin.buffer.read().split(separator) if value
        ]
        targets = select_image_targets(paths, packaging_only=args.packaging_only)

    print(f"matrix={matrix_json(targets)}")
    print(f"has_images={'true' if targets else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
