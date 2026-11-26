"""Global provider schema accounting and drift classification tests."""

from __future__ import annotations

import pytest
from fdai.delivery.provider_schema import (
    ProviderSchemaCoverage,
    ProviderSchemaCoverageStatus,
    ProviderSchemaDriftKind,
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    ProviderSchemaType,
    compare_provider_schema_snapshots,
)


def _type(
    resource_type: str,
    *,
    stable: tuple[str, ...] = ("2025-01-01",),
    preview: tuple[str, ...] = (),
    parent: str | None = None,
    writable: tuple[str, ...] = ("resourceGroup",),
    scope_evidence: bool = True,
) -> ProviderSchemaType:
    preferred = stable[-1] if stable else preview[-1]
    return ProviderSchemaType(
        resource_type=resource_type,
        stable_api_versions=stable,
        preview_api_versions=preview,
        preferred_api_version=preferred,
        source_document="generated/example/types.md",
        parent_type=parent,
        readable_scopes=("resourceGroup",),
        writable_scopes=writable,
        scope_evidence_available=scope_evidence,
    )


def _snapshot(*types: ProviderSchemaType, revision: str = "a" * 40) -> ProviderSchemaSnapshot:
    return ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision=revision,
        types=tuple(types),
    )


def test_snapshot_is_order_independent_and_content_addressed() -> None:
    first = _type("Microsoft.Example/widgets")
    second = _type(
        "Microsoft.Example/widgets/parts",
        parent="Microsoft.Example/widgets",
    )

    forward = _snapshot(first, second)
    reverse = _snapshot(second, first)

    assert forward == reverse
    assert forward.schema_digest.startswith("sha256:")
    assert forward.to_mapping()["grants_authority"] is False


def test_snapshot_rejects_missing_structural_parent() -> None:
    child = _type(
        "Microsoft.Example/widgets/parts",
        parent="Microsoft.Example/widgets",
    )

    with pytest.raises(ProviderSchemaError, match="missing parent"):
        _snapshot(child)


def test_coverage_accounts_for_every_type_with_explicit_disposition() -> None:
    parent = _type("Microsoft.Example/widgets")
    child = _type(
        "Microsoft.Example/widgets/parts",
        parent="Microsoft.Example/widgets",
    )
    read_only = _type("Microsoft.Example/reports", writable=())
    preview = _type("Microsoft.Example/previews", stable=(), preview=("2025-01-01-preview",))
    snapshot = _snapshot(parent, child, read_only, preview)

    coverage = ProviderSchemaCoverage.build(
        snapshot=snapshot,
        modeled_provider_types=frozenset({"microsoft.example/widgets"}),
    )

    statuses = {entry.resource_type: entry.status for entry in coverage.entries}
    assert len(statuses) == len(snapshot.types)
    assert statuses["microsoft.example/widgets"] is ProviderSchemaCoverageStatus.MODELED
    assert (
        statuses["microsoft.example/widgets/parts"] is ProviderSchemaCoverageStatus.STRUCTURAL_ONLY
    )
    assert statuses["microsoft.example/reports"] is ProviderSchemaCoverageStatus.READ_ONLY
    assert statuses["microsoft.example/previews"] is ProviderSchemaCoverageStatus.PREVIEW_ONLY
    assert coverage.modeled_count == 1


def test_global_coverage_retains_all_3405_types_including_unused_types() -> None:
    types = tuple(_type(f"Microsoft.Provider{index:04d}/resources") for index in range(3_405))
    snapshot = _snapshot(*types)

    coverage = ProviderSchemaCoverage.build(
        snapshot=snapshot,
        modeled_provider_types=frozenset(
            {
                "microsoft.provider0000/resources",
                "microsoft.provider3404/resources",
            }
        ),
    )

    assert len(snapshot.types) == 3_405
    assert len(coverage.entries) == 3_405
    assert coverage.modeled_count == 2
    assert (
        sum(
            entry.status is ProviderSchemaCoverageStatus.UNSUPPORTED_WITH_REASON
            for entry in coverage.entries
        )
        == 3_403
    )


def test_additive_type_and_versions_are_compatible() -> None:
    baseline = _snapshot(_type("Microsoft.Example/widgets"))
    observed = _snapshot(
        _type(
            "Microsoft.Example/widgets",
            stable=("2025-01-01", "2025-02-01"),
            preview=("2025-03-01-preview",),
        ),
        _type("Microsoft.Example/reports"),
        revision="b" * 40,
    )

    drift = compare_provider_schema_snapshots(baseline, observed)

    assert drift.kind is ProviderSchemaDriftKind.COMPATIBLE
    assert drift.added_types == ("microsoft.example/reports",)
    assert drift.added_stable_versions == ("microsoft.example/widgets@2025-02-01",)
    assert drift.added_preview_versions == ("microsoft.example/widgets@2025-03-01-preview",)


@pytest.mark.parametrize("remove_type", [False, True])
def test_stable_surface_removal_is_breaking(remove_type: bool) -> None:
    baseline = _snapshot(
        _type("Microsoft.Example/widgets", stable=("2025-01-01", "2025-02-01")),
        _type("Microsoft.Example/reports"),
    )
    observed_types = (
        (_type("Microsoft.Example/widgets", stable=("2025-02-01",)),)
        if remove_type
        else (
            _type("Microsoft.Example/widgets", stable=("2025-02-01",)),
            _type("Microsoft.Example/reports"),
        )
    )
    observed = _snapshot(*observed_types, revision="b" * 40)

    drift = compare_provider_schema_snapshots(baseline, observed)

    assert drift.kind is ProviderSchemaDriftKind.BREAKING
    if remove_type:
        assert drift.removed_types == ("microsoft.example/reports",)
    assert drift.removed_stable_versions == ("microsoft.example/widgets@2025-01-01",)
