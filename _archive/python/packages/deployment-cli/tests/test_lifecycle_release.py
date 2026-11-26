from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
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


@pytest.mark.parametrize("product", ["example-web", "example-worker", "fdai"])
def test_component_releases_do_not_fabricate_http_metadata(product: str) -> None:
    document = manifest(product)
    document.pop("workloads")
    document.update(
        schema_version=APPLICATION_COMPONENT_RELEASE_SCHEMA,
        components={"worker": {"image_digest": "sha256:" + "b" * 64}},
    )
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert isinstance(release, ApplicationRelease)
    assert release.schema_version == APPLICATION_COMPONENT_RELEASE_SCHEMA
    assert release.components == {"worker": "sha256:" + "b" * 64}
    assert release.workloads == {}
    assert release.digest == canonical_digest(document)
    assert release.to_mapping() == document
    assert parse_lifecycle_release_manifest(canonical_bytes(release.to_mapping())) == release
    with pytest.raises(TypeError):
        release.components["worker"] = "sha256:" + "c" * 64  # type: ignore[index]


@pytest.mark.parametrize(
    "components",
    [
        {},
        {"worker": {"image_digest": "latest"}},
        {"../worker": {"image_digest": "sha256:" + "b" * 64}},
        {"worker": {"image_digest": "sha256:" + "b" * 64, "port": 8080}},
        {"worker": {"image_digest": "sha256:" + "b" * 64, "privileged": True}},
        {f"worker-{i}": {"image_digest": "sha256:" + "b" * 64} for i in range(65)},
    ],
)
def test_component_contract_rejects_unbounded_or_executable_fields(
    components: dict[str, object],
) -> None:
    document = manifest()
    document.pop("workloads")
    document.update(schema_version=APPLICATION_COMPONENT_RELEASE_SCHEMA, components=components)
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))


def test_component_and_http_inventory_formats_cannot_be_mixed() -> None:
    document = {
        **manifest(),
        "schema_version": APPLICATION_COMPONENT_RELEASE_SCHEMA,
        "components": {"worker": {"image_digest": "sha256:" + "b" * 64}},
    }
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))
    document["schema_version"] = APPLICATION_RELEASE_SCHEMA
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))


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
        ("workloads", {"1frontend": {"image_digest": "sha256:" + "b" * 64}}),
        ("workloads", {"a" * 64: {"image_digest": "sha256:" + "b" * 64}}),
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


@pytest.mark.parametrize("component", ["a", "a1", "a-b", "a" * 63])
def test_service_compatible_names_include_the_exact_length_boundary(component: str) -> None:
    document = {**manifest(), "workloads": {component: {"image_digest": "sha256:" + "b" * 64}}}
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert isinstance(release, ApplicationRelease)
    assert set(release.workloads) == {component}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"one","schema_version":"two"}',
        b'{"schema_version":"one","workloads":{"a":{},"a":{}}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e400}',
        b'{"value":-1e400}',
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


def schema_default_manifest(default: object) -> dict[str, object]:
    schema = {
        "scale": {
            "default": default,
            "x-fdai-axis": "installation-path",
            "x-fdai-owner": "customer",
        }
    }
    return {
        **manifest(),
        "configuration_schema": {
            "format": "fdai.release-configuration-schema.v1",
            "release_version": "1.5.0",
            "schema_sha256": canonical_digest(schema),
            "keys": schema,
        },
    }


@pytest.mark.parametrize("default", [1.5, 1e200, -1e200])
def test_finite_schema_defaults_have_a_canonical_round_trip(default: float) -> None:
    document = schema_default_manifest(default)
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert release.to_mapping() == document
    assert parse_lifecycle_release_manifest(canonical_bytes(release.to_mapping())) == release


@pytest.mark.parametrize("exceeds_limit", [False, True])
def test_unicode_defaults_obey_the_canonical_decoder_size_limit(exceeds_limit: bool) -> None:
    limit = 1_048_576
    overhead = len(canonical_bytes(schema_default_manifest("")))
    count = (limit - overhead) // len(canonical_bytes("가")[1:-1])
    document = schema_default_manifest("가" * (count + int(exceeds_limit)))
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    assert len(raw) < limit
    assert (len(canonical_bytes(document)) > limit) is exceeds_limit
    if exceeds_limit:
        with pytest.raises(RuntimeReleaseError):
            parse_lifecycle_release_manifest(raw)
    else:
        release = parse_lifecycle_release_manifest(raw)
        assert release.to_mapping() == document
        assert parse_lifecycle_release_manifest(canonical_bytes(release.to_mapping())) == release


@pytest.mark.parametrize("default", [float("inf"), float("-inf")])
def test_exponent_overflow_cannot_hide_in_a_digest_matching_schema_default(
    default: float,
) -> None:
    raw = canonical_bytes(schema_default_manifest(default)).replace(b"Infinity", b"1e400")
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(raw)
