"""Provider schema review validation and Heimdall drift projection tests."""

from __future__ import annotations

import pytest
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_review import (
    provider_schema_drift_payload,
    validate_provider_schema_review_package,
)


def _package() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "provider-schema-drift-review",
        "provider": "azure",
        "source_revision": "a" * 40,
        "baseline_digest": "sha256:" + "1" * 64,
        "observed_digest": "sha256:" + "2" * 64,
        "drift_digest": "3" * 64,
        "drift_kind": "breaking",
        "added_types": ["microsoft.example/new"],
        "removed_types": ["microsoft.example/old"],
        "added_stable_versions": [],
        "removed_stable_versions": ["microsoft.example/widgets@2024-01-01"],
        "added_preview_versions": [],
        "removed_preview_versions": [],
        "type_count": 10,
        "modeled_count": 2,
        "coverage_status_counts": {"modeled": 2, "unsupported-with-reason": 8},
        "review_required": True,
        "grants_authority": False,
    }


def test_projects_digest_bound_shadow_drift_without_raw_schema() -> None:
    first = provider_schema_drift_payload(_package())
    second = provider_schema_drift_payload(_package())

    assert first == second
    assert first["producer_principal"] == "Heimdall"
    assert first["event_type"] == "provider.schema_drift"
    assert first["authority_ceiling"] == "shadow"
    assert first["review_required"] is True
    assert first["grants_authority"] is False
    assert first["added_type_count"] == 1
    assert "added_types" not in first


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("drift_kind", "unchanged", "MUST NOT create"),
        ("review_required", False, "authority boundary"),
        ("grants_authority", True, "authority boundary"),
        ("removed_types", [], "no stable removal"),
        ("coverage_status_counts", {"modeled": 2}, "incomplete"),
    ],
)
def test_rejects_unsafe_or_incomplete_review_packages(
    field: str,
    value: object,
    message: str,
) -> None:
    package = _package()
    package[field] = value
    if field == "removed_types":
        package["removed_stable_versions"] = []

    with pytest.raises(ProviderSchemaError, match=message):
        validate_provider_schema_review_package(package)


def test_rejects_extra_untrusted_fields() -> None:
    package = _package()
    package["raw_schema"] = {"secret": "not allowed"}

    with pytest.raises(ProviderSchemaError, match="fields are invalid"):
        validate_provider_schema_review_package(package)
