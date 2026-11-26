"""Reviewed full-authority development profile input for source deployment."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_host_state import replace_or_verify_private_json

_STAGED_SCHEMA = "fdai.development-authority-staged-input.v1"
_MAX_INPUT_BYTES = 256 * 1024
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
_SEMVER = re.compile(r"\d+\.\d+\.\d+")
_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "profile_id",
        "scope",
        "classification",
        "owner_principal",
        "executor_principal",
        "valid_from",
        "valid_until",
        "source_revision",
        "catalog_revision",
        "policy_revision",
        "registered_actions",
    }
)
_SCOPE_FIELDS = frozenset({"tenant_digest", "subscription_digest", "resource_group_digests"})
_ACTION_FIELDS = frozenset({"action_type", "version", "action_type_digest"})


@dataclass(frozen=True, slots=True)
class DevelopmentAuthorityDeploymentProfile:
    """Validated deployment input and exact executor binding."""

    profile: dict[str, object]
    profile_json: str
    executor_principal: str
    input_digest: str


def load_development_authority_profile(path: Path) -> DevelopmentAuthorityDeploymentProfile:
    """Load one operator-reviewed profile from a private local file."""

    return _from_mapping(_load_json_object(path, "development authority profile"), staged=False)


def staged_development_authority_profile_from_path(
    path: Path | None,
) -> DevelopmentAuthorityDeploymentProfile | None:
    """Load one digest-bound managed-host profile."""

    if path is None:
        return None
    return _from_mapping(
        _load_json_object(path, "staged development authority profile"),
        staged=True,
    )


def stage_development_authority_profile(
    value: DevelopmentAuthorityDeploymentProfile | None,
    *,
    tunnel: Any,
    prepared_root: Path,
    remote_root: str,
) -> tuple[str, ...]:
    """Copy one reviewed non-secret profile to the managed host."""

    if value is None:
        return ()
    local_path = prepared_root / "development-authority-profile.json"
    remote_path = f"{remote_root}/development-authority-profile.json"
    replace_or_verify_private_json(
        local_path,
        {
            "schema_version": _STAGED_SCHEMA,
            "input_digest": value.input_digest,
            "profile": value.profile,
        },
    )
    tunnel.copy_to(local_path, remote_path, timeout=120)
    return ("--development-authority-profile", remote_path)


def apply_development_authority_profile(
    values: dict[str, object],
    profile: DevelopmentAuthorityDeploymentProfile | None,
) -> None:
    """Bind a selected profile without revoking a retained profile on omission."""

    if profile is None:
        return
    values["development_authority_profile_json"] = profile.profile_json
    values["development_authority_executor_principal"] = profile.executor_principal


def clear_development_authority_profile(values: dict[str, object]) -> bool:
    """Remove a retained profile only for an explicit clear operation."""

    removed_profile = values.pop("development_authority_profile_json", None)
    removed_executor = values.pop("development_authority_executor_principal", None)
    return removed_profile is not None or removed_executor is not None


def validate_deployment_target(
    profile: DevelopmentAuthorityDeploymentProfile,
    *,
    tenant_id: str,
    subscription_id: str,
    resource_groups: tuple[str, ...],
    source_revision: str,
) -> None:
    """Require the reviewed profile to cover only the exact selected deployment target."""

    scope = _mapping(profile.profile["scope"], "development authority scope")
    expected_tenant = _scope_digest(tenant_id)
    expected_subscription = _scope_digest(subscription_id)
    if scope["tenant_digest"] != expected_tenant:
        raise ValueError("development authority profile tenant differs from the deployment target")
    if scope["subscription_digest"] != expected_subscription:
        raise ValueError(
            "development authority profile subscription differs from the deployment target"
        )
    allowed_groups = {_scope_digest(value) for value in resource_groups}
    selected_groups = set(_digest_list(scope["resource_group_digests"], "resource_group_digests"))
    if selected_groups and not selected_groups <= allowed_groups:
        raise ValueError(
            "development authority profile resource groups exceed the deployment target"
        )
    if profile.profile["source_revision"] != source_revision:
        raise ValueError("development authority profile source revision differs")


def _from_mapping(
    value: Mapping[str, Any], *, staged: bool
) -> DevelopmentAuthorityDeploymentProfile:
    if staged:
        if set(value) != {"schema_version", "input_digest", "profile"}:
            raise ValueError("staged development authority profile fields are invalid")
        if value.get("schema_version") != _STAGED_SCHEMA:
            raise ValueError("staged development authority profile schema is unsupported")
        profile = _profile(_mapping(value["profile"], "development authority profile"))
        input_digest = _input_digest(profile)
        if value.get("input_digest") != input_digest:
            raise ValueError("staged development authority profile digest differs")
    else:
        profile = _profile(value)
        input_digest = _input_digest(profile)
    profile_json = json.dumps(
        profile,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return DevelopmentAuthorityDeploymentProfile(
        profile=profile,
        profile_json=profile_json,
        executor_principal=str(profile["executor_principal"]),
        input_digest=input_digest,
    )


def _profile(value: Mapping[str, Any]) -> dict[str, object]:
    if set(value) != _PROFILE_FIELDS:
        raise ValueError("development authority profile fields are invalid")
    if value.get("schema_version") != "1.0.0":
        raise ValueError("development authority profile schema is unsupported")
    if value.get("classification") != "disposable_development":
        raise ValueError("development authority profile classification is invalid")
    profile_id = _identifier(value.get("profile_id"), "profile_id")
    owner = _text(value.get("owner_principal"), "owner_principal")
    executor = _text(value.get("executor_principal"), "executor_principal")
    if owner.strip().casefold() == executor.strip().casefold():
        raise ValueError("development Owner and executor principals MUST be distinct")
    valid_from = _aware_time(value.get("valid_from"), "valid_from")
    valid_until = _aware_time(value.get("valid_until"), "valid_until")
    if valid_from >= valid_until:
        raise ValueError("development authority profile interval is invalid")
    scope = _scope(_mapping(value.get("scope"), "development authority scope"))
    actions = _actions(value.get("registered_actions"))
    return {
        "schema_version": "1.0.0",
        "profile_id": profile_id,
        "scope": scope,
        "classification": "disposable_development",
        "owner_principal": owner,
        "executor_principal": executor,
        "valid_from": str(value["valid_from"]),
        "valid_until": str(value["valid_until"]),
        "source_revision": _revision(value.get("source_revision"), "source_revision"),
        "catalog_revision": _revision(value.get("catalog_revision"), "catalog_revision"),
        "policy_revision": _revision(value.get("policy_revision"), "policy_revision"),
        "registered_actions": actions,
    }


def _scope(value: Mapping[str, Any]) -> dict[str, object]:
    if set(value) != _SCOPE_FIELDS:
        raise ValueError("development authority scope fields are invalid")
    groups = _digest_list(value.get("resource_group_digests"), "resource_group_digests")
    if tuple(sorted(set(groups))) != groups:
        raise ValueError("development authority resource groups MUST be sorted and unique")
    return {
        "tenant_digest": _digest(value.get("tenant_digest"), "tenant_digest"),
        "subscription_digest": _digest(value.get("subscription_digest"), "subscription_digest"),
        "resource_group_digests": list(groups),
    }


def _actions(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("development authority registered actions are required")
    actions: list[dict[str, str]] = []
    identities: list[tuple[str, str, str]] = []
    for item in value:
        action = _mapping(item, "registered development action")
        if set(action) != _ACTION_FIELDS:
            raise ValueError("registered development action fields are invalid")
        name = _identifier(action.get("action_type"), "action_type")
        version = action.get("version")
        if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
            raise ValueError("registered development action version is invalid")
        digest = _digest(action.get("action_type_digest"), "action_type_digest")
        actions.append({"action_type": name, "version": version, "action_type_digest": digest})
        identities.append((name, version, digest))
    if len(set(identities)) != len(identities) or tuple(sorted(identities)) != tuple(identities):
        raise ValueError("registered development actions MUST be sorted and unique")
    return actions


def _scope_digest(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("development deployment scope identifier is empty")
    return "sha256:" + canonical_digest({"value": normalized})


def _input_digest(profile: Mapping[str, object]) -> str:
    return canonical_digest({"profile": profile})


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    raw = read_private_bytes(path, max_bytes=_MAX_INPUT_BYTES)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{description} must contain valid JSON") from exc
    return _mapping(value, description)


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{description} must contain a JSON object")
    return dict(value)


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"development authority {name} is invalid")
    return value


def _digest_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"development authority {name} must be a list")
    return tuple(_digest(item, name) for item in value)


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"development authority {name} is invalid")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"development authority {name} is invalid")
    return value


def _revision(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError(f"development authority {name} is invalid")
    return value


def _aware_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"development authority {name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"development authority {name} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"development authority {name} must be timezone-aware")
    return parsed


__all__ = [
    "DevelopmentAuthorityDeploymentProfile",
    "apply_development_authority_profile",
    "clear_development_authority_profile",
    "load_development_authority_profile",
    "stage_development_authority_profile",
    "staged_development_authority_profile_from_path",
    "validate_deployment_target",
]
