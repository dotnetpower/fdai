"""Pinned Azure REST relationship-schema evidence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.azure.provider_relationship_schema import (
    AzureRestApiRelationshipSchemaParser,
    GitAzureRestApiRelationshipSchemaSource,
    LocalAzureRestApiRelationshipSchemaSource,
)
from fdai.delivery.provider_schema import ProviderSchemaError

REVISION = "a" * 40
SCHEMA_DIGEST = "sha256:" + "b" * 64


def _write_spec(root: Path, *, allowed: object | None = None) -> Path:
    document = root / "specification" / "example" / "resource-manager" / "stable.json"
    document.parent.mkdir(parents=True)
    details = (
        {"allowedResources": [{"type": "Microsoft.Example/sources"}]}
        if allowed is None
        else {"allowedResources": allowed}
    )
    document.write_text(
        json.dumps(
            {
                "swagger": "2.0",
                "paths": {
                    (
                        "/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}"
                        "/providers/Microsoft.Example/widgets/{widgetName}"
                    ): {
                        "put": {
                            "parameters": [
                                {
                                    "name": "body",
                                    "in": "body",
                                    "schema": {"$ref": "#/definitions/Widget"},
                                }
                            ]
                        }
                    }
                },
                "definitions": {
                    "Widget": {
                        "type": "object",
                        "x-ms-azure-resource": True,
                        "properties": {"properties": {"$ref": "#/definitions/WidgetProperties"}},
                    },
                    "WidgetProperties": {
                        "type": "object",
                        "properties": {
                            "sourceId": {"$ref": "#/definitions/SourceResourceId"},
                            "unboundedId": {
                                "type": "string",
                                "format": "arm-id",
                                "description": "Microsoft.Fake/ignored is not evidence",
                            },
                        },
                    },
                    "SourceResourceId": {
                        "type": "string",
                        "format": "arm-id",
                        "x-ms-arm-id-details": details,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return document


def test_extracts_exact_and_unresolved_targets_with_operation_lineage(tmp_path: Path) -> None:
    _write_spec(tmp_path)

    snapshot = AzureRestApiRelationshipSchemaParser().parse(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
    )

    assert snapshot.extension_document_count == 1
    assert snapshot.exact_reference_count == 1
    assert snapshot.unresolved_reference_count == 1
    exact = next(item for item in snapshot.arm_id_references if item.resolved)
    assert exact.allowed_resource_types == ("microsoft.example/sources",)
    assert exact.unresolved_allowed_resources == ()
    assert exact.operation_paths == (
        "/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Example/widgets/{widgetName}",
    )
    assert exact.source_resource_types == ("microsoft.example/widgets",)
    unresolved = next(item for item in snapshot.arm_id_references if not item.resolved)
    assert unresolved.allowed_resource_types == ()
    assert len(snapshot.resource_definitions) == 1
    assert snapshot.to_mapping()["grants_authority"] is False


def test_does_not_infer_targets_from_descriptions(tmp_path: Path) -> None:
    _write_spec(tmp_path)

    snapshot = AzureRestApiRelationshipSchemaParser().parse(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
    )

    unresolved = next(item for item in snapshot.arm_id_references if not item.resolved)
    assert unresolved.allowed_resource_types == ()


def test_retains_nonstandard_allowed_resource_shape_as_unresolved(tmp_path: Path) -> None:
    _write_spec(tmp_path, allowed=[{"description": "missing exact type"}])

    snapshot = AzureRestApiRelationshipSchemaParser().parse(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
    )

    authored = next(
        item for item in snapshot.arm_id_references if item.unresolved_allowed_resources
    )
    assert authored.unresolved_allowed_resources == ('{"description":"missing exact type"}',)
    assert authored.resolved is False


def test_retains_non_exact_allowed_resource_value_as_unresolved(tmp_path: Path) -> None:
    _write_spec(tmp_path, allowed=[{"type": "*"}])

    snapshot = AzureRestApiRelationshipSchemaParser().parse(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
    )

    authored = next(
        item for item in snapshot.arm_id_references if item.unresolved_allowed_resources
    )
    assert authored.allowed_resource_types == ()
    assert authored.unresolved_allowed_resources == ("*",)
    assert authored.resolved is False


def test_rejects_mutable_revision_and_truncated_corpus(tmp_path: Path) -> None:
    _write_spec(tmp_path)
    parser = AzureRestApiRelationshipSchemaParser(min_document_count=2)

    with pytest.raises(ProviderSchemaError, match="immutable lowercase hex"):
        parser.parse(
            tree_root=tmp_path,
            source_revision="main",
            provider_schema_digest=SCHEMA_DIGEST,
        )
    with pytest.raises(ProviderSchemaError, match="complete-corpus bounds"):
        parser.parse(
            tree_root=tmp_path,
            source_revision=REVISION,
            provider_schema_digest=SCHEMA_DIGEST,
        )


async def test_local_source_collects_mounted_exact_revision(tmp_path: Path) -> None:
    _write_spec(tmp_path)

    snapshot = await LocalAzureRestApiRelationshipSchemaSource(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
        parser=AzureRestApiRelationshipSchemaParser(),
    ).collect()

    assert snapshot.source_revision == REVISION


async def test_git_source_uses_exact_revision_without_mutable_lookup(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_spec(corpus)
    resolved = False

    def resolve(repo_url: str, revision_ref: str, timeout_seconds: float) -> str:
        nonlocal resolved
        resolved = True
        return REVISION

    source = GitAzureRestApiRelationshipSchemaSource(
        repo_url="https://example.com/Azure/azure-rest-api-specs.git",
        revision_ref=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
        parser=AzureRestApiRelationshipSchemaParser(),
        revision_resolver=resolve,
        tree_fetcher=lambda _repo, _revision, _destination, _timeout: corpus,
    )

    snapshot = await source.collect()

    assert snapshot.source_revision == REVISION
    assert resolved is False


def test_scans_legacy_encoding_without_skipping_extension_evidence(tmp_path: Path) -> None:
    document = _write_spec(tmp_path)
    text = document.read_text(encoding="utf-8").replace(
        "Microsoft.Fake/ignored is not evidence",
        "Microsoft.Fake/ignored - legacy evidence note",
    )
    document.write_bytes(text.replace(" - ", " \N{EN DASH} ").encode("cp1252"))
    unrelated = document.parent / "unrelated.json"
    unrelated.write_bytes(b'{"description":"legacy \x96 text without extensions"}')

    snapshot = AzureRestApiRelationshipSchemaParser().parse(
        tree_root=tmp_path,
        source_revision=REVISION,
        provider_schema_digest=SCHEMA_DIGEST,
    )

    assert snapshot.extension_document_count == 1
    assert snapshot.exact_reference_count == 1
