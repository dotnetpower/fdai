"""Watcher-summary delivery orchestrator - fakes only, no live adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fdai.delivery.rule_catalog_delivery import deliver_watcher_summary
from fdai.rule_catalog.pipeline.review import (
    CollectionReviewPackage,
    CollectionReviewPublicationReceipt,
)
from fdai.rule_catalog.pipeline.snapshot_mirror import SnapshotMirror


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        self.calls.append(storage_ref)
        return True


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[CollectionReviewPackage] = []

    async def publish(self, package: CollectionReviewPackage) -> CollectionReviewPublicationReceipt:
        self.published.append(package)
        return CollectionReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref="example/fdai#9",
            already_existed=False,
        )


def _summary(snapshot_dir: Path) -> dict[str, Any]:
    return {
        "entries": [
            {
                "source_id": "example-source",
                "due": True,
                "collect_exit_code": 0,
                "collect": {
                    "source_id": "example-source",
                    "resolved_revision": "0" * 40,
                    "snapshot_dir": str(snapshot_dir),
                    "success_receipt": {
                        "source_id": "example-source",
                        "resolved_revision": "0" * 40,
                        "content_sha256": "1" * 64,
                        "license": "Apache-2.0",
                        "redistribution": "embeddable",
                        "verified_rules": 2,
                        "verified_at": "2026-07-06T00:00:00+00:00",
                    },
                },
            },
            {
                # not due - MUST be skipped, never touches mirror/publisher.
                "source_id": "other-source",
                "due": False,
            },
            {
                # collected but not verified (no success receipt) - skipped.
                "source_id": "unverified-source",
                "collect_exit_code": 0,
                "collect": {"snapshot_dir": str(snapshot_dir)},
            },
        ]
    }


def _snapshot_tree(tmp_path: Path) -> Path:
    snapshot_dir = tmp_path / "example-source" / ("0" * 40)
    tree = snapshot_dir / "tree"
    tree.mkdir(parents=True)
    (tree / "a.yaml").write_text("a: 1\n", encoding="utf-8")
    return snapshot_dir


async def test_delivers_only_verified_entries(tmp_path: Path) -> None:
    snapshot_dir = _snapshot_tree(tmp_path)
    store = _FakeStore()
    publisher = _FakePublisher()

    receipts = await deliver_watcher_summary(
        _summary(snapshot_dir),
        mirror=SnapshotMirror(store=store),
        publisher=publisher,
    )

    assert len(receipts) == 1
    (receipt,) = receipts
    assert receipt.source_id == "example-source"
    assert receipt.mirrored_file_count == 1
    assert receipt.review is not None
    assert receipt.review.review_ref == "example/fdai#9"
    assert store.calls == [f"rule-catalog-snapshots/example-source/{'0' * 40}/a.yaml"]
    assert len(publisher.published) == 1
    assert publisher.published[0].snapshot_files[0].storage_ref == store.calls[0]


async def test_skips_mirror_and_publisher_when_not_configured(tmp_path: Path) -> None:
    snapshot_dir = _snapshot_tree(tmp_path)

    receipts = await deliver_watcher_summary(_summary(snapshot_dir), mirror=None, publisher=None)

    assert len(receipts) == 1
    (receipt,) = receipts
    assert receipt.mirrored_file_count == 0
    assert receipt.review is None
