from __future__ import annotations

from copy import deepcopy

import pytest

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    NGINX_ACCEPTANCE_SCHEMA,
    NginxAcceptanceRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.runtime_release import RuntimeReleaseError, parse_runtime_release_manifest


def manifest() -> dict[str, object]:
    return {
        "schema_version": NGINX_ACCEPTANCE_SCHEMA,
        "release_version": "0.1.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "workloads": {"nginx": {"image_digest": "sha256:" + "b" * 64}},
    }


def test_nginx_is_not_disguised_as_an_fdai_runtime() -> None:
    document = manifest()
    release = parse_lifecycle_release_manifest(canonical_bytes(document))
    assert isinstance(release, NginxAcceptanceRelease)
    assert release.digest == canonical_digest(document)
    assert release.to_mapping() == document
    assert release.schema_target == 0
    assert release.schema_range.minimum == release.schema_range.maximum == 0
    assert release.capability_maximums == {}
    with pytest.raises(RuntimeReleaseError):
        parse_runtime_release_manifest(canonical_bytes(document))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source_commit", "not-a-commit"),
        ("platform_tag", "windows-x86_64"),
        ("release_version", "latest"),
        ("release_version", "01.0.0"),
        ("schema_version", "fdai.nginx-acceptance-release.v2"),
        ("services", {}),
        ("capabilities", {}),
        ("schema", {"target": 15}),
        ("installation_agents", {}),
        ("workloads", {"core-control-plane": {"image_digest": "sha256:" + "b" * 64}}),
        ("workloads", {"nginx": {"image_digest": "nginx:latest"}}),
        ("workloads", {"nginx": {"image_digest": "sha256:" + "B" * 64}}),
        ("workloads", {"nginx": {"image_digest": "sha256:" + "b" * 64, "command": []}}),
    ],
)
def test_acceptance_rejects_unbounded_or_unpinned_content(key: str, value: object) -> None:
    document = manifest()
    document[key] = value
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))


@pytest.mark.parametrize("key", list(manifest()))
def test_every_acceptance_field_is_required(key: str) -> None:
    document = manifest()
    del document[key]
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(document))


def test_acceptance_metadata_is_detached_from_caller_mutation() -> None:
    release = parse_lifecycle_release_manifest(canonical_bytes(manifest()))
    detached = deepcopy(release.to_mapping())
    detached["workloads"] = {}
    assert release.to_mapping() == manifest()


def test_duplicate_fields_and_oversized_documents_are_rejected() -> None:
    for raw in (b'{"schema_version":"a","schema_version":"b"}', b" " * (1024 * 1024 + 1)):
        with pytest.raises(RuntimeReleaseError):
            parse_lifecycle_release_manifest(raw)


@pytest.mark.parametrize("mismatch", [False, True])
def test_acceptance_reuses_the_exact_configuration_schema_binding(mismatch: bool) -> None:
    document = manifest()
    keys = {
        "replicas": {
            "default": 1,
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
    }
    document["configuration_schema"] = {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": "0.2.0" if mismatch else "0.1.0",
        "schema_sha256": canonical_digest(keys),
        "keys": keys,
    }
    if mismatch:
        with pytest.raises(RuntimeReleaseError):
            parse_lifecycle_release_manifest(canonical_bytes(document))
    else:
        schema = parse_lifecycle_release_manifest(canonical_bytes(document)).configuration_schema
        assert schema is not None
        assert schema.to_mapping() == keys
