"""Collection review package + receipt contract tests."""

from __future__ import annotations

import json

import pytest
from fdai.rule_catalog.pipeline.review import (
    CollectionReviewPackage,
    CollectionReviewPublicationReceipt,
    MirroredSnapshotFile,
)


def _package(**overrides: object) -> CollectionReviewPackage:
    defaults: dict[str, object] = {
        "source_id": "example-source",
        "resolved_revision": "0" * 40,
        "content_sha256": "1" * 64,
        "license": "Apache-2.0",
        "redistribution": "embeddable",
        "verified_rules": 3,
        "verified_at": "2026-07-06T00:00:00+00:00",
        "snapshot_files": (
            MirroredSnapshotFile(
                relative_path="a.yaml",
                storage_ref="rule-catalog-snapshots/example-source/0/a.yaml",
                digest="2" * 64,
            ),
        ),
    }
    defaults.update(overrides)
    return CollectionReviewPackage.build(**defaults)  # type: ignore[arg-type]


def test_build_is_content_addressed_and_deterministic() -> None:
    first = _package()
    second = _package()

    assert first.content_digest == second.content_digest
    assert len(first.content_digest) == 64


def test_build_digest_ignores_reverification_time_for_unchanged_content() -> None:
    first = _package(verified_at="2026-07-06T00:00:00+00:00")
    second = _package(verified_at="2026-08-29T00:00:00+00:00")

    assert first.content_digest == second.content_digest
    assert first.verified_at != second.verified_at


def test_build_digest_changes_when_snapshot_files_differ() -> None:
    first = _package()
    second = _package(snapshot_files=())

    assert first.content_digest != second.content_digest


def test_build_rejects_empty_identifiers() -> None:
    with pytest.raises(ValueError, match="source id and revision"):
        _package(source_id="")


def test_publication_receipt_requires_sha256_digest() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        CollectionReviewPublicationReceipt(
            package_digest="not-a-digest",
            review_ref="example/repo#1",
            already_existed=False,
        )


def test_publication_receipt_rejects_whitespace_ref() -> None:
    with pytest.raises(ValueError, match="bounded printable ASCII"):
        CollectionReviewPublicationReceipt(
            package_digest="a" * 64,
            review_ref="example/repo #1",
            already_existed=False,
        )


def test_package_material_round_trips_through_json() -> None:
    package = _package()
    material = {
        "source_id": package.source_id,
        "snapshot_files": [
            {"relative_path": f.relative_path, "storage_ref": f.storage_ref, "digest": f.digest}
            for f in package.snapshot_files
        ],
    }
    assert json.loads(json.dumps(material)) == material
