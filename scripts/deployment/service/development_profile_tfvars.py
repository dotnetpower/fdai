"""Full-authority development profile validation for service Terraform inputs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
_SEMVER = re.compile(r"\d+\.\d+\.\d+")
_FIELDS = {
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


class DevelopmentProfileTfvarsError(ValueError):
    """Raised when a service deployment profile input is invalid."""


def selected_profile_json(raw_json: str | None) -> str:
    """Resolve the explicit or ambient development profile input."""

    return (
        os.environ.get("FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON", "").strip()
        if raw_json is None
        else raw_json
    )


def bind_development_profile(
    materialized: dict[str, Any],
    *,
    service: str,
    environment: str,
    raw_json: str | None,
    approval_profile_json: str | None,
) -> None:
    """Attach one canonical development profile and its distinct executor."""

    selected = selected_profile_json(raw_json)
    if not selected:
        return
    if approval_profile_json:
        raise DevelopmentProfileTfvarsError(
            "production and development approval profiles are mutually exclusive"
        )
    if service != "core-control-plane" or environment != "dev":
        raise DevelopmentProfileTfvarsError(
            "full-authority development profile is valid only for Core in dev"
        )
    try:
        payload = json.loads(selected)
    except json.JSONDecodeError as exc:
        raise DevelopmentProfileTfvarsError(
            "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON must contain valid JSON"
        ) from exc
    profile = _profile(payload)
    materialized["development_authority_profile_json"] = json.dumps(
        profile,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    materialized["development_authority_executor_principal"] = profile["executor_principal"]


def _profile(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise DevelopmentProfileTfvarsError("development authority profile fields are invalid")
    if value.get("schema_version") != "1.0.0":
        raise DevelopmentProfileTfvarsError("development authority profile schema is unsupported")
    if value.get("classification") != "disposable_development":
        raise DevelopmentProfileTfvarsError(
            "development authority profile classification is invalid"
        )
    _identifier(value.get("profile_id"), "profile_id")
    owner = _text(value.get("owner_principal"), "owner_principal")
    executor = _text(value.get("executor_principal"), "executor_principal")
    if owner.strip().casefold() == executor.strip().casefold():
        raise DevelopmentProfileTfvarsError(
            "development Owner and executor principals MUST be distinct"
        )
    valid_from = _aware_time(value.get("valid_from"), "valid_from")
    valid_until = _aware_time(value.get("valid_until"), "valid_until")
    if valid_from >= valid_until:
        raise DevelopmentProfileTfvarsError("development authority interval is invalid")
    _scope(value.get("scope"))
    _revision(value.get("source_revision"), "source_revision")
    _revision(value.get("catalog_revision"), "catalog_revision")
    _revision(value.get("policy_revision"), "policy_revision")
    _actions(value.get("registered_actions"))
    return {str(key): member for key, member in value.items()}


def _scope(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "tenant_digest",
        "subscription_digest",
        "resource_group_digests",
    }:
        raise DevelopmentProfileTfvarsError("development authority scope fields are invalid")
    _digest(value.get("tenant_digest"), "tenant_digest")
    _digest(value.get("subscription_digest"), "subscription_digest")
    groups = value.get("resource_group_digests")
    if not isinstance(groups, list):
        raise DevelopmentProfileTfvarsError("resource_group_digests must be a list")
    normalized = tuple(_digest(item, "resource_group_digest") for item in groups)
    if tuple(sorted(set(normalized))) != normalized:
        raise DevelopmentProfileTfvarsError(
            "development authority resource groups MUST be sorted and unique"
        )


def _actions(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise DevelopmentProfileTfvarsError("development authority registered actions are required")
    identities: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "action_type",
            "version",
            "action_type_digest",
        }:
            raise DevelopmentProfileTfvarsError("registered development action fields are invalid")
        name = _identifier(item.get("action_type"), "action_type")
        version = item.get("version")
        if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
            raise DevelopmentProfileTfvarsError("registered development action version is invalid")
        digest = _digest(item.get("action_type_digest"), "action_type_digest")
        identities.append((name, version, digest))
    if len(set(identities)) != len(identities) or tuple(sorted(identities)) != tuple(identities):
        raise DevelopmentProfileTfvarsError(
            "registered development actions MUST be sorted and unique"
        )


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid")
    return value


def _revision(value: object, name: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid")


def _aware_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DevelopmentProfileTfvarsError(f"development authority {name} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DevelopmentProfileTfvarsError(f"development authority {name} must be timezone-aware")
    return parsed


__all__ = [
    "DevelopmentProfileTfvarsError",
    "bind_development_profile",
    "selected_profile_json",
]
