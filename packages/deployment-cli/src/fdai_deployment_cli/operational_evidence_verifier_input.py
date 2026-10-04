"""Reviewed deployment input for the optional operational evidence verifier."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_host_state import replace_or_verify_private_json

_SCHEMA = "fdai.operational-evidence-verifier-deployment-input.v1"
_STAGED_SCHEMA = "fdai.operational-evidence-verifier-staged-input.v1"
_MAX_INPUT_BYTES = 256 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_RESOURCE_SCOPE = re.compile(r"/subscriptions/[^/]+(?:/resourceGroups/[^/]+/providers/.+)?")
_FIXED_VERIFIER_ROLE = "fdai_operational_evidence_verifier"
_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "trust_registry_path",
        "trust_registry_pin",
        "grant_registry_path",
        "grant_registry_pin",
        "anchors",
        "caller_token_issuer",
        "caller_token_audience",
        "caller_token_jwks",
        "role_readback_scopes",
        "allowed_role_scopes",
        "vertical_executor_principal_ids",
        "writer_members",
        "dev_gateway_executor_principal_id",
        "verifier_database_role",
    }
)
_ANCHORS_FIELDS = frozenset({"schema_version", "venue", "anchors"})
_ANCHOR_FIELDS = frozenset({"anchor_id", "principal_id", "evidence_class"})
_BINDING_FIELDS = frozenset(
    {
        "enabled",
        "trust_registry_path",
        "trust_registry_pin",
        "grant_registry_path",
        "grant_registry_pin",
        "anchors_json",
        "caller_token_issuer",
        "caller_token_audience",
        "caller_token_jwks_json",
        "role_readback_scopes_json",
        "allowed_role_scopes_json",
        "vertical_executor_principals_json",
        "writer_members_json",
        "dev_gateway_executor_principal_id",
    }
)
_SECRET_JWK_FIELDS = frozenset({"d", "p", "q", "dp", "dq", "qi", "k"})
_ALLOWED_ROLE_NAMES = frozenset(
    {"AcrPull", "Key Vault Secrets User", "Reader", "Monitoring Reader"}
)


@dataclass(frozen=True, slots=True)
class OperationalEvidenceVerifierDeploymentInput:
    """Validated authority-neutral binding for the read-only verifier workload."""

    binding: dict[str, object]
    input_digest: str


def load_operational_evidence_verifier_input(
    path: Path,
) -> OperationalEvidenceVerifierDeploymentInput:
    """Load one private reviewed verifier input from the operator-selected path."""

    raw = load_json_object(
        read_private_bytes(path, max_bytes=_MAX_INPUT_BYTES),
        label="operational evidence verifier deployment input",
        max_bytes=_MAX_INPUT_BYTES,
    )
    return _from_mapping(raw, staged=False)


def staged_operational_evidence_verifier_input_from_path(
    path: Path | None,
) -> OperationalEvidenceVerifierDeploymentInput | None:
    """Load a staged managed-host input, or report that the verifier was not selected."""

    if path is None:
        return None
    raw = load_json_object(
        read_private_bytes(path, max_bytes=_MAX_INPUT_BYTES),
        label="staged operational evidence verifier deployment input",
        max_bytes=_MAX_INPUT_BYTES,
    )
    return _from_mapping(raw, staged=True)


def stage_operational_evidence_verifier_input(
    value: OperationalEvidenceVerifierDeploymentInput | None,
    *,
    tunnel: Any,
    prepared_root: Path,
    remote_root: str,
) -> tuple[str, ...]:
    """Copy the reviewed non-secret input to the managed host and return CLI arguments."""

    if value is None:
        return ()
    staged: dict[str, object] = {
        "schema_version": _STAGED_SCHEMA,
        "input_digest": value.input_digest,
        "binding": value.binding,
    }
    local_path = prepared_root / "operational-evidence-verifier-input.json"
    remote_path = f"{remote_root}/operational-evidence-verifier-input.json"
    replace_or_verify_private_json(local_path, staged)
    tunnel.copy_to(local_path, remote_path, timeout=120)
    return ("--operational-evidence-verifier-input", remote_path)


def apply_operational_evidence_verifier_input(
    values: dict[str, object],
    verifier_input: OperationalEvidenceVerifierDeploymentInput | None,
) -> None:
    """Populate Terraform and application values only when the input is selected."""

    if verifier_input is None:
        return
    values["enable_operational_evidence_verifier"] = True
    values["operational_evidence_verifier"] = dict(verifier_input.binding)


def _from_mapping(
    value: Mapping[str, Any], *, staged: bool
) -> OperationalEvidenceVerifierDeploymentInput:
    if staged:
        if set(value) != {"schema_version", "input_digest", "binding"}:
            raise ValueError("operational evidence verifier input fields are invalid")
        if value.get("schema_version") != _STAGED_SCHEMA:
            raise ValueError("operational evidence verifier input schema is unsupported")
        binding = _staged_binding(
            _mapping(value["binding"], "operational evidence verifier binding")
        )
        material = {
            "schema_version": _SCHEMA,
            **_input_material_from_binding(binding),
        }
        digest = canonical_digest(material)
        if value.get("input_digest") != digest:
            raise ValueError("operational evidence verifier input digest differs")
        return OperationalEvidenceVerifierDeploymentInput(binding=binding, input_digest=digest)
    if set(value) != _TOP_FIELDS:
        raise ValueError("operational evidence verifier input fields are invalid")
    if value.get("schema_version") != _SCHEMA:
        raise ValueError("operational evidence verifier input schema is unsupported")
    _reject_secret_material(value)
    binding = _binding(value)
    material = {
        "schema_version": _SCHEMA,
        **_input_material_from_binding(binding),
    }
    return OperationalEvidenceVerifierDeploymentInput(
        binding=binding,
        input_digest=canonical_digest(material),
    )


def _staged_binding(value: Mapping[str, Any]) -> dict[str, object]:
    if set(value) != _BINDING_FIELDS or value.get("enabled") is not True:
        raise ValueError("operational evidence verifier binding fields are invalid")
    anchors = _anchors(_json_field(value, "anchors_json"))
    caller_jwks = _caller_jwks(_json_field(value, "caller_token_jwks_json"))
    readback_scopes = _scopes(
        _json_field(value, "role_readback_scopes_json"), "role_readback_scopes"
    )
    allowed_role_scopes = _allowed_role_scopes(_json_field(value, "allowed_role_scopes_json"))
    vertical_principals = _guid_list(
        _json_field(value, "vertical_executor_principals_json"),
        "vertical_executor_principal_ids",
    )
    writer_members = _writer_members(_json_field(value, "writer_members_json"))
    return {
        "enabled": True,
        "trust_registry_path": _path_text(value, "trust_registry_path"),
        "trust_registry_pin": _digest(value, "trust_registry_pin"),
        "grant_registry_path": _path_text(value, "grant_registry_path"),
        "grant_registry_pin": _digest(value, "grant_registry_pin"),
        "anchors_json": _json_text(anchors),
        "caller_token_issuer": _https_url(value, "caller_token_issuer"),
        "caller_token_audience": _audience(value, "caller_token_audience"),
        "caller_token_jwks_json": _json_text(caller_jwks),
        "role_readback_scopes_json": _json_text(readback_scopes),
        "allowed_role_scopes_json": _json_text(allowed_role_scopes),
        "vertical_executor_principals_json": _json_text(vertical_principals),
        "writer_members_json": _json_text(writer_members),
        "dev_gateway_executor_principal_id": _guid(value, "dev_gateway_executor_principal_id"),
    }


def _binding(value: Mapping[str, Any]) -> dict[str, object]:
    trust_pin = _digest(value, "trust_registry_pin")
    grant_pin = _digest(value, "grant_registry_pin")
    anchors = _anchors(value["anchors"])
    caller_jwks = _caller_jwks(value["caller_token_jwks"])
    readback_scopes = _scopes(value["role_readback_scopes"], "role_readback_scopes")
    allowed_role_scopes = _allowed_role_scopes(value["allowed_role_scopes"])
    vertical_principals = _guid_list(
        value["vertical_executor_principal_ids"],
        "vertical_executor_principal_ids",
    )
    writer_members = _writer_members(value["writer_members"])
    verifier_role = _text(value, "verifier_database_role")
    if verifier_role != _FIXED_VERIFIER_ROLE:
        raise ValueError("operational evidence verifier database role is fixed")
    return {
        "enabled": True,
        "trust_registry_path": _path_text(value, "trust_registry_path"),
        "trust_registry_pin": trust_pin,
        "grant_registry_path": _path_text(value, "grant_registry_path"),
        "grant_registry_pin": grant_pin,
        "anchors_json": _json_text(anchors),
        "caller_token_issuer": _https_url(value, "caller_token_issuer"),
        "caller_token_audience": _audience(value, "caller_token_audience"),
        "caller_token_jwks_json": _json_text(caller_jwks),
        "role_readback_scopes_json": _json_text(readback_scopes),
        "allowed_role_scopes_json": _json_text(allowed_role_scopes),
        "vertical_executor_principals_json": _json_text(vertical_principals),
        "writer_members_json": _json_text(writer_members),
        "dev_gateway_executor_principal_id": _guid(value, "dev_gateway_executor_principal_id"),
    }


def _input_material_from_binding(binding: Mapping[str, object]) -> dict[str, object]:
    return {
        "trust_registry_path": binding["trust_registry_path"],
        "trust_registry_pin": binding["trust_registry_pin"],
        "grant_registry_path": binding["grant_registry_path"],
        "grant_registry_pin": binding["grant_registry_pin"],
        "anchors": json.loads(str(binding["anchors_json"])),
        "caller_token_issuer": binding["caller_token_issuer"],
        "caller_token_audience": binding["caller_token_audience"],
        "caller_token_jwks": json.loads(str(binding["caller_token_jwks_json"])),
        "role_readback_scopes": json.loads(str(binding["role_readback_scopes_json"])),
        "allowed_role_scopes": json.loads(str(binding["allowed_role_scopes_json"])),
        "vertical_executor_principal_ids": json.loads(
            str(binding["vertical_executor_principals_json"])
        ),
        "writer_members": json.loads(str(binding["writer_members_json"])),
        "dev_gateway_executor_principal_id": binding["dev_gateway_executor_principal_id"],
        "verifier_database_role": _FIXED_VERIFIER_ROLE,
    }


def _anchors(value: object) -> dict[str, object]:
    data = _mapping(value, "operational evidence anchors")
    if set(data) != _ANCHORS_FIELDS or data.get("schema_version") != "1.0.0":
        raise ValueError("operational evidence anchors fields are invalid")
    if data.get("venue") != "deployed":
        raise ValueError("operational evidence anchors must target deployed venue")
    items = data.get("anchors")
    if not isinstance(items, list) or not items:
        raise ValueError("operational evidence anchors must be a non-empty list")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in items:
        anchor = _mapping(item, "operational evidence anchor")
        if set(anchor) != _ANCHOR_FIELDS:
            raise ValueError("operational evidence anchor fields are invalid")
        anchor_id = _bounded_text(anchor, "anchor_id")
        principal = _principal_text(anchor.get("principal_id"), "principal_id")
        evidence_class = _bounded_text(anchor, "evidence_class")
        if not anchor_id.startswith("anchor:"):
            raise ValueError("operational evidence anchor id is invalid")
        if evidence_class != "live":
            raise ValueError("operational evidence anchors must use live evidence")
        if anchor_id in seen:
            raise ValueError("operational evidence anchor is duplicated")
        seen.add(anchor_id)
        normalized.append(
            {
                "anchor_id": anchor_id,
                "principal_id": principal,
                "evidence_class": evidence_class,
            }
        )
    return {"schema_version": "1.0.0", "venue": "deployed", "anchors": normalized}


def _caller_jwks(value: object) -> dict[str, object]:
    jwks = _mapping(value, "caller token JWKS")
    if set(jwks) != {"keys"}:
        raise ValueError("caller token JWKS fields are invalid")
    keys = jwks["keys"]
    if not isinstance(keys, list) or not keys:
        raise ValueError("caller token JWKS must contain at least one public key")
    normalized: list[dict[str, object]] = []
    for item in keys:
        key = _mapping(item, "caller token JWK")
        if _SECRET_JWK_FIELDS & set(key):
            raise ValueError("caller token JWKS contains secret key material")
        if key.get("kty") in {"oct", "dir"}:
            raise ValueError("caller token JWKS contains secret key material")
        if not isinstance(key.get("kty"), str) or not str(key["kty"]).strip():
            raise ValueError("caller token JWK is malformed")
        normalized.append({str(name): member for name, member in key.items()})
    return {"keys": normalized}


def _allowed_role_scopes(value: object) -> dict[str, list[str]]:
    data = _mapping(value, "allowed role scopes")
    if not data:
        raise ValueError("allowed role scopes are required")
    normalized: dict[str, list[str]] = {}
    for role, scopes in data.items():
        if role not in _ALLOWED_ROLE_NAMES:
            raise ValueError("allowed role scopes include an unsupported role")
        normalized[role] = _scopes(scopes, f"allowed scopes for {role}")
    return normalized


def _writer_members(value: object) -> list[str]:
    if value != [_FIXED_VERIFIER_ROLE]:
        raise ValueError(
            "operational evidence writer members must contain only the verifier writer"
        )
    return [_FIXED_VERIFIER_ROLE]


def _guid_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list of GUIDs")
    return [_principal_text(item, label) for item in value]


def _scopes(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    scopes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} entries must be strings")
        scope = item.strip().rstrip("/")
        if _RESOURCE_SCOPE.fullmatch(scope) is None or "00000000-0000-0000-0000-" in scope:
            raise ValueError(f"{label} entries must be exact Azure resource scopes")
        _reject_placeholder(scope, label)
        scopes.append(scope)
    if len(scopes) != len(set(scopes)):
        raise ValueError(f"{label} entries must be unique")
    return scopes


def _digest(value: Mapping[str, Any], field: str) -> str:
    item = _text(value, field)
    if _DIGEST.fullmatch(item) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    _reject_placeholder(item, field)
    return item


def _guid(value: Mapping[str, Any], field: str) -> str:
    return _principal_text(value.get(field), field)


def _principal_text(value: object, field: str) -> str:
    if not isinstance(value, str) or _GUID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a GUID")
    _reject_placeholder(value, field)
    return value


def _path_text(value: Mapping[str, Any], field: str) -> str:
    item = _text(value, field)
    if not item or "\x00" in item or ".." in Path(item).parts or item in {"/", ".", "config"}:
        raise ValueError(f"{field} is invalid")
    _reject_placeholder(item, field)
    return item


def _https_url(value: Mapping[str, Any], field: str) -> str:
    item = _text(value, field)
    if not item.startswith("https://") or " " in item or item.endswith("example.com"):
        raise ValueError(f"{field} must be an HTTPS URL")
    _reject_placeholder(item, field)
    return item


def _audience(value: Mapping[str, Any], field: str) -> str:
    item = _text(value, field)
    if not item.startswith("api://") or len(item) > 256:
        raise ValueError(f"{field} is invalid")
    _reject_placeholder(item, field)
    return item


def _text(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{field} is required")
    return item.strip()


def _bounded_text(value: Mapping[str, Any], field: str) -> str:
    item = _text(value, field)
    if len(item) > 256:
        raise ValueError(f"{field} is too long")
    _reject_placeholder(item, field)
    return item


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return value


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_field(value: Mapping[str, Any], field: str) -> object:
    raw = _text(value, field)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc


def _reject_placeholder(value: str, field: str) -> None:
    lowered = value.casefold()
    if (
        set(value) <= {"0", "-"}
        or "replace" in lowered
        or "placeholder" in lowered
        or "set-me" in lowered
        or "<" in value
        or ">" in value
    ):
        raise ValueError(f"{field} contains a placeholder value")


def _reject_secret_material(value: object) -> None:
    if isinstance(value, Mapping):
        if any(key.casefold() in {"password", "client_secret", "private_key"} for key in value):
            raise ValueError("operational evidence verifier input contains secret material")
        for item in value.values():
            _reject_secret_material(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_material(item)
    elif isinstance(value, str):
        lowered = value.casefold()
        if "private key" in lowered or "client_secret" in lowered or "password=" in lowered:
            raise ValueError("operational evidence verifier input contains secret material")


__all__ = [
    "OperationalEvidenceVerifierDeploymentInput",
    "apply_operational_evidence_verifier_input",
    "load_operational_evidence_verifier_input",
    "stage_operational_evidence_verifier_input",
    "staged_operational_evidence_verifier_input_from_path",
]
