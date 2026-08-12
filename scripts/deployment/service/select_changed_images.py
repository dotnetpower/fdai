from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ImageTarget:
    service: str
    dockerfile: str
    image: str


IMAGE_TARGETS = (
    ImageTarget(
        service="core-control-plane",
        dockerfile="services/core-control-plane/docker/Dockerfile",
        image="fdai-core-control-plane",
    ),
    ImageTarget(
        service="operator-service",
        dockerfile="services/operator-service/docker/Dockerfile",
        image="fdai-operator-service",
    ),
    ImageTarget(
        service="document-ingestion-api",
        dockerfile="services/document-ingestion-api/docker/Dockerfile",
        image="fdai-document-ingestion-api",
    ),
    ImageTarget(
        service="document-processing-worker",
        dockerfile="services/document-processing-worker/docker/Dockerfile",
        image="fdai-document-processing-worker",
    ),
    ImageTarget(
        service="isolated-executor",
        dockerfile="services/isolated-executor/docker/Dockerfile",
        image="fdai-isolated-executor",
    ),
)

_ALL_TARGET_EXACT_PATHS = {
    ".dockerignore",
    ".github/workflows/container-supply-chain.yml",
    ".trivyignore.yaml",
    "LICENSE",
    "README.md",
    "pyproject.toml",
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
    *(f"services/{target.service}/pyproject.toml" for target in IMAGE_TARGETS),
}
_CORE_EXACT_PATHS = {
    "alembic.ini",
    "docs/internals/sregym-absorption-ledger.json",
}
_CORE_PREFIXES = (
    "alembic/",
    "config/",
    "policies/",
    "rule-catalog/",
    "services/assets/",
    "tests/scenarios/",
)


def select_image_targets(changed_paths: Iterable[str]) -> tuple[ImageTarget, ...]:
    """Return every image whose tracked Docker build input changed."""
    paths = {path.removeprefix("./") for path in changed_paths if path}
    if any(
        path in _ALL_TARGET_EXACT_PATHS
        or path in _ALL_TARGET_METADATA_PATHS
        or path.startswith(_ALL_TARGET_PREFIXES)
        for path in paths
    ):
        return IMAGE_TARGETS

    selected: set[str] = set()
    for path in paths:
        if path in _CORE_EXACT_PATHS or path.startswith(_CORE_PREFIXES):
            selected.add("core-control-plane")
        if path == "config/agent-stewardship.yaml":
            selected.add("document-ingestion-api")
        if not path.startswith("services/") or path.startswith("services/assets/"):
            continue

        matching_services = {
            target.service
            for target in IMAGE_TARGETS
            if path.startswith(f"services/{target.service}/")
        }
        if not matching_services:
            return IMAGE_TARGETS
        selected.update(matching_services)

    return tuple(target for target in IMAGE_TARGETS if target.service in selected)


def matrix_json(targets: Iterable[ImageTarget]) -> str:
    """Render a compact GitHub Actions matrix payload."""
    return json.dumps(
        {"include": [asdict(target) for target in targets]},
        separators=(",", ":"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", dest="select_all")
    parser.add_argument("--nul", action="store_true")
    args = parser.parse_args()

    if args.select_all:
        targets = IMAGE_TARGETS
    else:
        separator = b"\0" if args.nul else b"\n"
        paths = [
            value.decode("utf-8") for value in sys.stdin.buffer.read().split(separator) if value
        ]
        targets = select_image_targets(paths)

    print(f"matrix={matrix_json(targets)}")
    print(f"has_images={'true' if targets else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
