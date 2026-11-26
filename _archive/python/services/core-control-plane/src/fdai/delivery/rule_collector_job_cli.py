"""Container Apps Job entry point for verified rule collection evidence."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import redirect_stdout
from typing import Any

import httpx

from fdai.delivery.azure.rule_catalog_snapshot_store import (
    AzureBlobRuleCatalogSnapshotConfig,
    AzureBlobRuleCatalogSnapshotStore,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter, GitOpsPrConfig
from fdai.delivery.gitops_pr.collection_review import GitOpsCollectionReviewPublisher
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.rule_catalog_delivery import deliver_watcher_summary
from fdai.rule_catalog.pipeline.collect import CollectorSuccessReceipt
from fdai.rule_catalog.pipeline.review import CollectionReviewPublisher
from fdai.rule_catalog.pipeline.snapshot_mirror import SnapshotMirror
from fdai.rule_catalog.pipeline.watcher_cli import main as watcher_main
from fdai.shared.providers.state_store import StateStore

_SUCCESS_STATE_PREFIX = "runtime:collector-success:"


def build_delivery_adapters(
    env: Mapping[str, str],
    *,
    http_client: httpx.AsyncClient,
) -> tuple[SnapshotMirror | None, CollectionReviewPublisher | None]:
    """Construct the optional durable-mirror and review-PR adapters from env.

    Presence of ``FDAI_RULE_CATALOG_SNAPSHOT_CONTAINER_URL`` opts into the
    durable snapshot mirror; presence of ``FDAI_GITOPS_TOKEN`` opts into
    review-only PR publication - the same presence-gated pattern
    :func:`fdai.runtime.delivery._build_publisher` already uses for the
    core app's remediation-PR backend. Both stay ``None`` (the exact
    behavior before this function existed) when their env vars are unset,
    so a default job with no delivery configured is unaffected.

    Neither branch performs I/O here - constructing an adapter only reads
    env and wraps ``http_client``; the first live request happens inside
    :func:`fdai.delivery.rule_catalog_delivery.deliver_watcher_summary`.
    """
    mirror: SnapshotMirror | None = None
    container_url = env.get("FDAI_RULE_CATALOG_SNAPSHOT_CONTAINER_URL", "").strip()
    if container_url:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=http_client, env=env)
        blob_store = AzureBlobRuleCatalogSnapshotStore(
            config=AzureBlobRuleCatalogSnapshotConfig(container_url=container_url),
            identity=identity,
            http_client=http_client,
        )
        mirror = SnapshotMirror(store=blob_store)

    publisher: CollectionReviewPublisher | None = None
    token = env.get("FDAI_GITOPS_TOKEN", "").strip()
    if token:
        owner = env.get("FDAI_GITOPS_OWNER", "").strip()
        repo = env.get("FDAI_GITOPS_REPO", "").strip()
        if not owner or not repo:
            raise RuntimeError(
                "FDAI_GITOPS_TOKEN is set but FDAI_GITOPS_OWNER / FDAI_GITOPS_REPO are "
                "missing; both are required to publish review-only collection PRs."
            )
        gitops = GitOpsPrAdapter(
            config=GitOpsPrConfig(owner=owner, repo=repo),
            http_client=http_client,
            token=token,
        )
        publisher = GitOpsCollectionReviewPublisher(publisher=gitops)

    return mirror, publisher


def _delivery_configured(env: Mapping[str, str]) -> bool:
    return bool(
        env.get("FDAI_RULE_CATALOG_SNAPSHOT_CONTAINER_URL", "").strip()
        or env.get("FDAI_GITOPS_TOKEN", "").strip()
    )


async def _deliver(summary: MutableMapping[str, Any], *, env: Mapping[str, str]) -> None:
    """Durably mirror + review-publish this run's verified sources, if configured."""
    async with httpx.AsyncClient() as http_client:
        mirror, publisher = build_delivery_adapters(env, http_client=http_client)
        receipts = await deliver_watcher_summary(summary, mirror=mirror, publisher=publisher)
    summary["delivery"] = [
        {
            "source_id": receipt.source_id,
            "resolved_revision": receipt.resolved_revision,
            "mirrored_file_count": receipt.mirrored_file_count,
            "review": (
                None
                if receipt.review is None
                else {
                    "package_digest": receipt.review.package_digest,
                    "review_ref": receipt.review.review_ref,
                    "already_existed": receipt.review.already_existed,
                }
            ),
        }
        for receipt in receipts
    ]


async def record_success_receipts(
    store: StateStore,
    summary: Mapping[str, Any],
) -> int:
    """Persist each validated receipt and its audit row exactly once."""
    entries = summary.get("entries")
    if not isinstance(entries, list):
        raise ValueError("collector watcher summary MUST contain entries")
    recorded = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("collect_exit_code") != 0:
            continue
        collect = entry.get("collect")
        if not isinstance(collect, dict):
            continue
        raw_receipt = collect.get("success_receipt")
        if raw_receipt is None:
            continue
        if not isinstance(raw_receipt, dict):
            raise ValueError("collector success receipt MUST be an object")
        receipt = CollectorSuccessReceipt.from_mapping(raw_receipt)
        canonical = json.dumps(
            receipt.to_mapping(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        idempotency_key = f"rule-collector-success:{digest}"
        created = await store.write_state_with_audit_if_absent(
            f"{_SUCCESS_STATE_PREFIX}{receipt.source_id}:{digest}",
            receipt.to_mapping(),
            {
                "kind": "rule_collector.success",
                "event_id": digest,
                "correlation_id": None,
                "tier": "t0",
                "decision": "succeeded",
                "idempotency_key": idempotency_key,
                "actor_identity": "runtime.rule-collector",
                "timestamp": receipt.verified_at.isoformat(),
                "mode": "shadow",
                "rollback_reference": None,
                "source_id": receipt.source_id,
                "resolved_revision": receipt.resolved_revision,
                "content_sha256": receipt.content_sha256,
                "license": receipt.license,
                "redistribution": receipt.redistribution,
                "verified_rules": receipt.verified_rules,
            },
        )
        recorded += int(created)
    return recorded


def main(
    argv: Sequence[str] | None = None,
    *,
    store: StateStore | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run the verified watcher and durably record every successful source."""
    arguments = list(argv if argv is not None else sys.argv[1:])
    if "--verify" not in arguments:
        arguments.append("--verify")
    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = watcher_main(arguments)
    raw_summary = captured.getvalue()
    try:
        summary = json.loads(raw_summary)
    except json.JSONDecodeError:
        print(raw_summary, end="")
        return exit_code or 2
    if exit_code != 0:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return exit_code
    try:
        state_store = store or _store_from_environment()
        summary["recorded_success_receipts"] = asyncio.run(
            record_success_receipts(state_store, summary)
        )
    except Exception as exc:  # noqa: BLE001 - never expose provider details from a batch job
        print(
            f"error: collector success persistence failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    environment = env if env is not None else os.environ
    if _delivery_configured(environment):
        try:
            asyncio.run(_deliver(summary, env=environment))
        except Exception as exc:  # noqa: BLE001 - never expose provider details from a batch job
            print(
                f"error: rule-catalog delivery failed: {type(exc).__name__}",
                file=sys.stderr,
            )
            return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _store_from_environment() -> StateStore:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN is required for collector success evidence")
    return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["build_delivery_adapters", "main", "record_success_receipts"]
