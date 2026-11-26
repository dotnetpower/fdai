from __future__ import annotations

import json

import pytest
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    RuntimeReleaseError,
    parse_lifecycle_release_manifest,
)


def _manifest(*, migration_class: str = "expand") -> dict[str, object]:
    return {
        "schema_version": "fdai.application-release.v2",
        "product": "fdai",
        "release_version": "1.2.3",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "components": {
            "core-control-plane": {"image_digest": "sha256:" + "b" * 64},
        },
        "schema": {
            "target": 2,
            "tolerates": {"minimum": 1, "maximum": 2},
        },
        "schema_expand": {
            "schema_version": "fdai.schema-expand-job.v1",
            "classification": {
                "schema": "fdai.migration-classification.v1",
                "revisions": {"revision_2": migration_class},
            },
            "active_deadline_seconds": 1800,
        },
    }


def test_component_release_accepts_bounded_expand_job() -> None:
    release = parse_lifecycle_release_manifest(
        json.dumps(_manifest(), sort_keys=True, separators=(",", ":")).encode()
    )

    assert isinstance(release, ApplicationRelease)
    assert release.schema_expand is not None
    assert release.schema_expand.classification == {"revision_2": "expand"}
    assert release.schema_expand.active_deadline_seconds == 1800


@pytest.mark.parametrize(
    "change",
    [
        {"migration_class": "contract"},
        {"deadline": 30},
        {"schema_target": 0},
    ],
)
def test_component_release_rejects_unsafe_expand_job(change: dict[str, object]) -> None:
    document = _manifest(migration_class=str(change.get("migration_class", "expand")))
    if "deadline" in change:
        document["schema_expand"]["active_deadline_seconds"] = change["deadline"]  # type: ignore[index]
    if "schema_target" in change:
        document["schema"]["target"] = change["schema_target"]  # type: ignore[index]

    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )
