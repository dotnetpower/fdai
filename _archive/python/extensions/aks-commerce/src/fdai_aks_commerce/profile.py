"""Load the immutable AKS commerce topology and SLO resources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from jsonschema import Draft202012Validator

_RESOURCE_PACKAGE = "fdai_aks_commerce.resources"
_MANIFEST = "manifest.json"


class AksCommerceProfileError(ValueError):
    """A packaged scenario resource failed deterministic validation."""


@dataclass(frozen=True, slots=True)
class AksCommerceResource:
    """Verified package-relative resource and immutable content."""

    resource_id: str
    kind: str
    path: str
    sha256: str
    content: bytes


def load_resource_bytes(path: str) -> bytes:
    """Read one package-relative resource without consulting the repository."""

    parts = path.split("/")
    if not path or any(part in {"", ".", ".."} for part in parts):
        raise AksCommerceProfileError("AKS commerce resource path must be package-relative")
    resource = files(_RESOURCE_PACKAGE).joinpath(*parts)
    if not resource.is_file():
        raise AksCommerceProfileError(f"AKS commerce resource {path!r} does not exist")
    return resource.read_bytes()


def load_resource_manifest() -> dict[str, Any]:
    """Load the canonical inert package resource manifest."""

    try:
        manifest = json.loads(load_resource_bytes(_MANIFEST))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AksCommerceProfileError("AKS commerce manifest must be valid UTF-8 JSON") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0.0"
        or manifest.get("package_id") != "aks-commerce"
        or manifest.get("candidate_state") != "inert"
        or not isinstance(manifest.get("resources"), list)
    ):
        raise AksCommerceProfileError("AKS commerce manifest shape is invalid")
    return manifest


def load_resources() -> tuple[AksCommerceResource, ...]:
    """Verify every declared package resource in canonical id order."""

    manifest = load_resource_manifest()
    resources: list[AksCommerceResource] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for raw in manifest["resources"]:
        if not isinstance(raw, dict) or set(raw) != {"id", "kind", "path", "sha256"}:
            raise AksCommerceProfileError("AKS commerce resource declaration is invalid")
        resource_id = str(raw["id"])
        kind = str(raw["kind"])
        path = str(raw["path"])
        sha256 = str(raw["sha256"])
        if resource_id in ids or path in paths:
            raise AksCommerceProfileError("AKS commerce resource ids and paths must be unique")
        if kind not in {"profile", "slo", "workflow"}:
            raise AksCommerceProfileError("AKS commerce resource kind is unsupported")
        content = load_resource_bytes(path)
        if hashlib.sha256(content).hexdigest() != sha256:
            raise AksCommerceProfileError(f"AKS commerce resource digest mismatch: {resource_id}")
        resources.append(AksCommerceResource(resource_id, kind, path, sha256, content))
        ids.add(resource_id)
        paths.add(path)
    if [resource.resource_id for resource in resources] != sorted(ids):
        raise AksCommerceProfileError("AKS commerce resources must use canonical id order")
    return tuple(resources)


def load_slo_documents() -> tuple[dict[str, Any], ...]:
    """Validate and return every packaged workload SLO declaration."""

    validator = Draft202012Validator(dict(PackageResourceSchemaRegistry().get("slo")))
    documents: list[dict[str, Any]] = []
    for resource in load_resources():
        if resource.kind != "slo":
            continue
        value = yaml.safe_load(resource.content)
        if not isinstance(value, dict):
            raise AksCommerceProfileError(f"{resource.path} must contain a YAML object")
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            first = errors[0]
            where = ".".join(str(part) for part in first.absolute_path) or "<root>"
            raise AksCommerceProfileError(f"{resource.path}: {where}: {first.message}")
        documents.append(value)
    return tuple(documents)


def load_scenario_profile() -> dict[str, Any]:
    """Return the validated topology profile."""

    profiles = tuple(resource for resource in load_resources() if resource.kind == "profile")
    if len(profiles) != 1:
        raise AksCommerceProfileError("AKS commerce package requires exactly one profile")
    try:
        value = json.loads(profiles[0].content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AksCommerceProfileError("AKS commerce profile must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AksCommerceProfileError("AKS commerce profile must contain a JSON object")
    _validate_profile(value)
    return value


def _validate_profile(value: dict[str, Any]) -> None:
    expected = {"schema_version", "profile_id", "services", "workloads", "links", "slos"}
    if set(value) != expected or value["schema_version"] != "1.0.0":
        raise AksCommerceProfileError("AKS commerce profile shape is invalid")
    services = value["services"]
    workloads = value["workloads"]
    links = value["links"]
    slos = value["slos"]
    if not all(isinstance(items, list) for items in (services, workloads, links, slos)):
        raise AksCommerceProfileError("AKS commerce profile collections must be arrays")
    service_ids = _unique_ids(services, "service")
    workload_ids = _unique_ids(workloads, "workload")
    slo_ids = _unique_ids(slos, "SLO")
    if service_ids != {"catalog-browse", "order-fulfillment"}:
        raise AksCommerceProfileError("AKS commerce profile service ids are invalid")
    for link in links:
        if not isinstance(link, dict) or set(link) != {"from_id", "link_type", "to_id"}:
            raise AksCommerceProfileError("AKS commerce profile link is invalid")
        link_type = link["link_type"]
        if link_type == "implemented_by":
            valid = link["from_id"] in service_ids and link["to_id"] in workload_ids
        elif link_type == "workload_depends_on":
            valid = link["from_id"] in workload_ids and link["to_id"] in workload_ids
        elif link_type == "service_has_service_objective":
            valid = link["from_id"] in service_ids and link["to_id"] in slo_ids
        else:
            valid = False
        if not valid:
            raise AksCommerceProfileError("AKS commerce profile link target is invalid")


def _unique_ids(items: list[object], label: str) -> set[str]:
    values: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise AksCommerceProfileError(f"AKS commerce {label} declaration is invalid")
        values.append(item["id"])
    if len(values) != len(set(values)):
        raise AksCommerceProfileError(f"AKS commerce {label} ids must be unique")
    return set(values)


__all__ = [
    "AksCommerceProfileError",
    "AksCommerceResource",
    "load_resource_bytes",
    "load_resource_manifest",
    "load_resources",
    "load_scenario_profile",
    "load_slo_documents",
]
