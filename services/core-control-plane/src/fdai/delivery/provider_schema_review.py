"""Validate inert provider-schema reviews and project deterministic Heimdall drift signals."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TypeGuard, cast

from fdai.delivery.provider_schema import ProviderSchemaDriftKind, ProviderSchemaError

_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SHA_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "provider",
        "source_revision",
        "baseline_digest",
        "observed_digest",
        "drift_digest",
        "drift_kind",
        "added_types",
        "removed_types",
        "added_stable_versions",
        "removed_stable_versions",
        "added_preview_versions",
        "removed_preview_versions",
        "type_count",
        "modeled_count",
        "coverage_status_counts",
        "review_required",
        "grants_authority",
    }
)


def validate_provider_schema_review_package(
    raw: Mapping[str, object],
) -> dict[str, object]:
    """Return a strict normalized copy or reject an untrusted review package."""

    if set(raw) != _REQUIRED_KEYS:
        raise ProviderSchemaError("provider schema review package fields are invalid")
    if raw["schema_version"] != "1.0.0" or raw["kind"] != "provider-schema-drift-review":
        raise ProviderSchemaError("provider schema review package identity is invalid")
    provider = raw["provider"]
    revision = raw["source_revision"]
    if not isinstance(provider, str) or not provider or not provider.isascii():
        raise ProviderSchemaError("provider schema review provider is invalid")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ProviderSchemaError("provider schema review source revision is invalid")
    for key in ("baseline_digest", "observed_digest"):
        digest = raw[key]
        if not isinstance(digest, str) or not _SHA_DIGEST.fullmatch(digest):
            raise ProviderSchemaError(f"provider schema review {key} is invalid")
    drift_digest = raw["drift_digest"]
    if not isinstance(drift_digest, str) or not _HEX_DIGEST.fullmatch(drift_digest):
        raise ProviderSchemaError("provider schema review drift digest is invalid")
    try:
        drift_kind = ProviderSchemaDriftKind(str(raw["drift_kind"]))
    except ValueError as exc:
        raise ProviderSchemaError("provider schema review drift kind is invalid") from exc
    if drift_kind is ProviderSchemaDriftKind.UNCHANGED:
        raise ProviderSchemaError("unchanged provider schema MUST NOT create a review package")
    list_fields = (
        "added_types",
        "removed_types",
        "added_stable_versions",
        "removed_stable_versions",
        "added_preview_versions",
        "removed_preview_versions",
    )
    normalized_lists: dict[str, list[str]] = {}
    for key in list_fields:
        value = raw[key]
        if not _is_string_sequence(value):
            raise ProviderSchemaError(f"provider schema review {key} is invalid")
        normalized = sorted(value)
        if normalized != list(value) or len(normalized) != len(set(normalized)):
            raise ProviderSchemaError(f"provider schema review {key} MUST be sorted and unique")
        normalized_lists[key] = normalized
    if drift_kind is ProviderSchemaDriftKind.BREAKING and not (
        normalized_lists["removed_types"] or normalized_lists["removed_stable_versions"]
    ):
        raise ProviderSchemaError("breaking provider schema review has no stable removal")
    type_count = raw["type_count"]
    modeled_count = raw["modeled_count"]
    status_counts = raw["coverage_status_counts"]
    if (
        not isinstance(type_count, int)
        or isinstance(type_count, bool)
        or type_count < 1
        or not isinstance(modeled_count, int)
        or isinstance(modeled_count, bool)
        or not 0 <= modeled_count <= type_count
        or not isinstance(status_counts, Mapping)
        or not status_counts
    ):
        raise ProviderSchemaError("provider schema review coverage summary is invalid")
    normalized_status_counts: dict[str, int] = {}
    for key, value in status_counts.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ProviderSchemaError("provider schema review coverage counts are invalid")
        normalized_status_counts[key] = value
    if sum(normalized_status_counts.values()) != type_count:
        raise ProviderSchemaError("provider schema review coverage counts are incomplete")
    if raw["review_required"] is not True or raw["grants_authority"] is not False:
        raise ProviderSchemaError("provider schema review authority boundary is invalid")
    return {
        key: (
            normalized_lists[key]
            if key in normalized_lists
            else dict(sorted(normalized_status_counts.items()))
            if key == "coverage_status_counts"
            else raw[key]
        )
        for key in sorted(raw)
    }


def provider_schema_drift_payload(raw: Mapping[str, object]) -> dict[str, object]:
    """Project one strict package into Heimdall's existing Drift ownership boundary."""

    package = validate_provider_schema_review_package(raw)
    provider = str(package["provider"])
    drift_digest = str(package["drift_digest"])
    added_types = cast(list[str], package["added_types"])
    removed_types = cast(list[str], package["removed_types"])
    removed_stable_versions = cast(list[str], package["removed_stable_versions"])
    return {
        "producer_principal": "Heimdall",
        "kind": "provider_schema",
        "event_type": "provider.schema_drift",
        "correlation_id": f"provider-schema:{provider}:{drift_digest}",
        "idempotency_key": f"provider-schema-drift:{drift_digest}",
        "resource_id": f"provider-schema://{provider}",
        "target_type": "provider-schema-catalog",
        "decision": package["drift_kind"],
        "authority_ceiling": "shadow",
        "baseline_digest": package["baseline_digest"],
        "observed_digest": package["observed_digest"],
        "drift_digest": drift_digest,
        "source_revision": package["source_revision"],
        "type_count": package["type_count"],
        "modeled_count": package["modeled_count"],
        "added_type_count": len(added_types),
        "removed_type_count": len(removed_types),
        "removed_stable_version_count": len(removed_stable_versions),
        "review_required": True,
        "grants_authority": False,
    }


def _is_string_sequence(value: object) -> TypeGuard[Sequence[str]]:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(item, str) for item in value)
    )


__all__ = ["provider_schema_drift_payload", "validate_provider_schema_review_package"]
