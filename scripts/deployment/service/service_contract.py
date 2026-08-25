#!/usr/bin/env python3
"""Resolve the closed five-service deployment contract."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPT_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_ROOT.parents[2]
_MATRIX_PATH = _SCRIPT_ROOT / "service-matrix.json"
_MIGRATION_PATH = _REPO_ROOT / "infra" / "services" / "state-migration.json"
_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class ServiceContractError(ValueError):
    """Raised when deployment input is outside the closed service contract."""


@dataclass(frozen=True)
class ServiceContract:
    """Resolved immutable deployment properties for one service and environment."""

    service: str
    environment: str
    terraform_root: str
    backend_key: str
    allowed_resource_address: str
    image_repository: str
    entrypoint: str
    required_environment: tuple[str, ...]


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ServiceContractError(f"{path.name} must contain a JSON object")
    return payload


def load_matrix() -> dict[str, Any]:
    """Load and cross-check the deployment matrix against state migration ownership."""
    matrix = _load_object(_MATRIX_PATH)
    migration = _load_object(_MIGRATION_PATH)
    if matrix.get("schema_version") != "1.0.0":
        raise ServiceContractError("service matrix schema_version must be 1.0.0")
    services = matrix.get("services")
    migration_services = migration.get("services")
    if not isinstance(services, dict) or not isinstance(migration_services, dict):
        raise ServiceContractError("service matrix and migration services must be objects")
    expected = {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    if set(services) != expected or set(migration_services) != expected:
        raise ServiceContractError("service matrix must contain exactly the five runtime services")
    for service, raw in services.items():
        if not isinstance(raw, dict):
            raise ServiceContractError(f"service matrix entry for {service} must be an object")
        template = raw.get("backend_key_template")
        migration_key = migration_services[service].get("backend_key")
        normalized_template = (
            template.replace("{environment}", "<environment>")
            if isinstance(template, str)
            else None
        )
        if normalized_template != migration_key:
            raise ServiceContractError(
                f"backend key mapping for {service} disagrees with state migration metadata"
            )
        moves = migration_services[service].get("moves")
        destinations = (
            {move.get("to") for move in moves if isinstance(move, dict)}
            if isinstance(moves, list)
            else set()
        )
        if raw.get("allowed_resource_address") not in destinations:
            raise ServiceContractError(
                f"allowed resource address for {service} disagrees with state migration metadata"
            )
    return matrix


def resolve_service(service: str, environment: str) -> ServiceContract:
    """Resolve a validated service selection to its isolated Terraform contract."""
    if environment not in _ENVIRONMENTS:
        raise ServiceContractError("environment must be dev, staging, or prod")
    services = load_matrix()["services"]
    raw = services.get(service)
    if not isinstance(raw, dict):
        raise ServiceContractError("service must be one of the five independent runtime services")
    fields = (
        "terraform_root",
        "backend_key_template",
        "allowed_resource_address",
        "image_repository",
        "entrypoint",
    )
    if any(not isinstance(raw.get(field), str) or not raw[field] for field in fields):
        raise ServiceContractError(f"service matrix entry for {service} is incomplete")
    required_environment = raw.get("required_environment")
    if (
        not isinstance(required_environment, list)
        or not required_environment
        or not all(isinstance(name, str) and name for name in required_environment)
        or len(set(required_environment)) != len(required_environment)
    ):
        raise ServiceContractError(
            f"service matrix entry for {service} has an invalid environment contract"
        )
    terraform_root = raw["terraform_root"]
    if not (_REPO_ROOT / terraform_root).is_dir():
        raise ServiceContractError(f"Terraform root for {service} does not exist")
    return ServiceContract(
        service=service,
        environment=environment,
        terraform_root=terraform_root,
        backend_key=raw["backend_key_template"].format(environment=environment),
        allowed_resource_address=raw["allowed_resource_address"],
        image_repository=raw["image_repository"],
        entrypoint=raw["entrypoint"],
        required_environment=tuple(required_environment),
    )


def validate_image_reference(contract: ServiceContract, repository: str, reference: str) -> str:
    """Require the selected service's GHCR subject pinned to one SHA-256 digest."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ServiceContractError("repository must be an owner/name pair")
    expected_prefix = f"ghcr.io/{repository.lower()}/{contract.image_repository}@"
    if not reference.startswith(expected_prefix):
        raise ServiceContractError("image reference does not match the selected service repository")
    digest = reference.removeprefix(expected_prefix)
    if _DIGEST_PATTERN.fullmatch(digest) is None:
        raise ServiceContractError("image reference must be pinned by a lowercase sha256 digest")
    return digest


def _write_github_output(path: Path, contract: ServiceContract, image_digest: str) -> None:
    values = {
        "allowed_resource_address": contract.allowed_resource_address,
        "backend_key": contract.backend_key,
        "image_digest": image_digest,
        "terraform_root": contract.terraform_root,
    }
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main() -> int:
    """Validate workflow inputs and emit resolved values for later steps."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = resolve_service(args.service, args.environment)
        image_digest = validate_image_reference(contract, args.repository, args.image)
        _write_github_output(args.github_output, contract, image_digest)
    except (OSError, json.JSONDecodeError, ServiceContractError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
