"""Durable mirror + review-only PR delivery for one verified collector run.

Composes :class:`fdai.rule_catalog.pipeline.snapshot_mirror.SnapshotMirror`
(durable snapshot location) with
:class:`fdai.rule_catalog.pipeline.review.CollectionReviewPublisher`
(review-only PR publication) against the already-verified success receipts
one watcher run produced. Both dependencies are injected Protocols; this
module never imports Azure or GitHub transport code directly, matching the
existing delivery-adapter DI boundary the rest of ``rule_catalog/pipeline/``
already uses (see ``promotion.py``).

This module never mutates ``rule-catalog/catalog`` or
``rule-catalog/baselines``, and never touches a secret value - callers hand
it already-authenticated adapters constructed once at process start from
environment-referenced credentials (see ``rule_collector_job_cli.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.rule_catalog.pipeline.review import (
    CollectionReviewPackage,
    CollectionReviewPublicationReceipt,
    CollectionReviewPublisher,
    MirroredSnapshotFile,
)
from fdai.rule_catalog.pipeline.snapshot_mirror import MirroredFile, SnapshotMirror


@dataclass(frozen=True, slots=True)
class SourceDeliveryReceipt:
    """Per-source outcome for one watcher run's durable delivery step."""

    source_id: str
    resolved_revision: str
    mirrored_file_count: int
    review: CollectionReviewPublicationReceipt | None


async def deliver_watcher_summary(
    summary: Mapping[str, Any],
    *,
    mirror: SnapshotMirror | None,
    publisher: CollectionReviewPublisher | None,
) -> tuple[SourceDeliveryReceipt, ...]:
    """Durably mirror and review-publish every successfully collected source.

    Read-only over ``summary`` (the exact JSON
    :func:`fdai.rule_catalog.pipeline.watcher_cli.main` already printed);
    never re-invokes the collector, never selects which source is due.
    Returns one receipt per source that produced a validated success
    receipt, in the summary's own entry order.

    ``mirror`` / ``publisher`` of ``None`` skips that stage for every
    entry - the default job (no delivery configured) behaves exactly as it
    did before this module existed.
    """
    entries = summary.get("entries")
    if not isinstance(entries, list):
        raise ValueError("watcher summary MUST contain entries")

    receipts: list[SourceDeliveryReceipt] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("collect_exit_code") != 0:
            continue
        collect = entry.get("collect")
        if not isinstance(collect, dict):
            continue
        raw_receipt = collect.get("success_receipt")
        if not isinstance(raw_receipt, dict):
            continue

        source_id = str(raw_receipt["source_id"])
        resolved_revision = str(raw_receipt["resolved_revision"])

        mirrored_files: tuple[MirroredFile, ...] = ()
        if mirror is not None:
            snapshot_dir = Path(str(collect["snapshot_dir"])) / "tree"
            mirror_receipt = await mirror.mirror(
                source_id=source_id,
                resolved_revision=resolved_revision,
                snapshot_dir=snapshot_dir,
            )
            mirrored_files = mirror_receipt.files

        review_receipt: CollectionReviewPublicationReceipt | None = None
        if publisher is not None:
            package = CollectionReviewPackage.build(
                source_id=source_id,
                resolved_revision=resolved_revision,
                content_sha256=str(raw_receipt["content_sha256"]),
                license=str(raw_receipt["license"]),
                redistribution=str(raw_receipt["redistribution"]),
                verified_rules=int(raw_receipt["verified_rules"]),
                verified_at=str(raw_receipt["verified_at"]),
                snapshot_files=tuple(
                    MirroredSnapshotFile(
                        relative_path=file.relative_path,
                        storage_ref=file.storage_ref,
                        digest=file.digest,
                    )
                    for file in mirrored_files
                ),
            )
            review_receipt = await publisher.publish(package)

        receipts.append(
            SourceDeliveryReceipt(
                source_id=source_id,
                resolved_revision=resolved_revision,
                mirrored_file_count=len(mirrored_files),
                review=review_receipt,
            )
        )
    return tuple(receipts)


__all__ = ["SourceDeliveryReceipt", "deliver_watcher_summary"]
