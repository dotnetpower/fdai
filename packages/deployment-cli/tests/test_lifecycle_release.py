from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_RELEASE_SCHEMA,
    ApplicationRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.runtime_release import RuntimeReleaseError, parse_runtime_release_manifest


def manifest(product: str = "example-web") -> dict[str, object]:
    return {
        "schema_version": APPLICATION_RELEASE_SCHEMA,
        "product": product,
        "release_version": "1.5.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "workloads": {
            "frontend": {
                "image_digest": "sha256:" + "b" * 64,
                "port": 9090,
                "health_path": "/ready",
                "replicas": 2,
            },
            "backend": {"image_digest": "sha256:" + "c" * 64},
        },
    }


@pytest.mark.parametrize("product", ["example-web", "example-worker", "fdai"])
def test_arbitrary_applications_use_the_same_validated_contract(product: str) -> None:
    document = manifest(product)
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert isinstance(release, ApplicationRelease)
    assert release.product == product
    assert release.digest == canonical_digest(document)
    assert release.workloads["frontend"].port == 9090
    assert release.workloads["frontend"].health_path == "/ready"
    assert release.workloads["frontend"].replicas == 2
    assert release.workloads["backend"].port == 8080
    assert release.schema_target == 0
    assert release.schema_range.contains(0)
    detached = release.to_mapping()
    detached["product"] = "changed"
    assert release.to_mapping() == document
    with pytest.raises(RuntimeReleaseError):
        parse_runtime_release_manifest(canonical_bytes(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product", ""),
        ("product", "../example"),
        ("product", True),
        ("release_version", "latest"),
        ("source_commit", "main"),
        ("platform_tag", "unknown"),
        ("workloads", {}),
        ("workloads", {"unknown": {"image_digest": "latest"}}),
        ("workloads", {"../escape": {"image_digest": "sha256:" + "b" * 64}}),
        ("workloads", {"a": {"image_digest": "sha256:" + "b" * 64, "port": True}}),
        ("workloads", {"a": {"image_digest": "sha256:" + "b" * 64, "port": 65536}}),
        ("workloads", {"a": {"image_digest": "sha256:" + "b" * 64, "health_path": "//host"}}),
        ("workloads", {"a": {"image_digest": "sha256:" + "b" * 64, "replicas": 0}}),
        ("workloads", {"a": {"image_digest": "sha256:" + "b" * 64, "privileged": True}}),
        ("schema", {"target": True, "tolerates": {"minimum": 0, "maximum": 2}}),
        ("schema", {"target": 2, "tolerates": {"minimum": 3, "maximum": 4}}),
        ("schema", None),
        ("unknown", "not accepted"),
    ],
)
def test_invalid_application_metadata_is_rejected(field: str, value: object) -> None:
    document = {**manifest(), field: value}
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))


def test_declared_database_compatibility_is_preserved() -> None:
    document = {
        **manifest(),
        "schema": {"target": 7, "tolerates": {"minimum": 5, "maximum": 8}},
    }
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert release.schema_target == 7
    assert release.schema_range is not None
    assert release.schema_range.contains(6)
    assert not release.schema_range.contains(4)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"one","schema_version":"two"}',
        b'{"schema_version":"one","workloads":{"a":{},"a":{}}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"[]",
        b"{}" * 600_000,
        '{"product":"example"}'.encode("utf-16"),
    ],
)
def test_all_manifest_boundaries_use_strict_bounded_utf8(raw: bytes) -> None:
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(raw)


def test_duplicate_workload_fields_do_not_publish_unstaggable_artifacts() -> None:
    raw = json.dumps(manifest()).replace('"port": 9090', '"port": 8080, "port": 9090').encode()
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(raw)
