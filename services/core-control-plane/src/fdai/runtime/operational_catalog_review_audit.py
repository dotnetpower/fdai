"""Durable intent and terminal ledger around catalog-review publication."""

from __future__ import annotations

from fdai.core.operational_learning import (
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogReviewPublisher,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "catalog-review-publication:"


class StateStoreAuditedCatalogReviewPublisher:
    """Persist exact intent before GitOps and terminal readback after it."""

    def __init__(
        self,
        *,
        downstream: CatalogReviewPublisher,
        state_store: StateStore,
    ) -> None:
        self._downstream = downstream
        self._store = state_store

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        key = _PREFIX + package.content_digest
        intent = {
            "kind": "catalog_review_publication_intent",
            "package_digest": package.content_digest,
            "candidate_digest": package.candidate.digest,
            "mode": "shadow",
            "draft_required": True,
            "grants_authority": False,
        }
        await self._write_exact(
            key + ":intent",
            intent,
            principal="Mimir",
            phase="intent",
        )
        receipt = await self._downstream.publish(package)
        terminal: dict[str, object] = {
            "kind": "catalog_review_publication_terminal",
            "package_digest": receipt.package_digest,
            "candidate_digest": receipt.candidate_digest,
            "review_ref": receipt.review_ref,
            "binding_digest": receipt.binding_digest,
            "observation_digest": receipt.observation_digest,
            "required_labels": list(receipt.required_labels),
            "observed_labels": list(receipt.observed_labels),
            "head_sha": receipt.head_sha,
            "review_document_digest": receipt.review_document_digest,
            "state": "open_draft_observed",
            "grants_authority": False,
        }
        await self._write_exact(
            key + ":terminal",
            terminal,
            principal="Mimir",
            phase="terminal",
        )
        return receipt

    async def _write_exact(
        self,
        key: str,
        value: dict[str, object],
        *,
        principal: str,
        phase: str,
    ) -> None:
        await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                **value,
                "actor": "Saga",
                "principal": principal,
                "phase": phase,
            },
        )
        retained = await self._store.read_state(key)
        if retained != value:
            raise ValueError("catalog review durable publication idempotency conflict")


__all__ = ["StateStoreAuditedCatalogReviewPublisher"]
