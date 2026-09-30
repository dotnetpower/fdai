from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.mimir_catalog_identity import (
    RECORD_KIND,
    STATE_PREFIX,
    required_digest,
    state_key,
    validate_identity,
)
from fdai.agents._framework.mimir_catalog_identity import idempotency_key as journal_idempotency_key
from fdai.core.operational_learning import (
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
)
from fdai.shared.providers.state_store import StateStore

_TERMINAL_STATUSES = frozenset({"invalidated", "published"})
_TERMINAL_RECEIPT_RETAIN = 5_000


class MimirCatalogReviewJournal:
    def __init__(self, store: StateStore | None, *, capacity: int) -> None:
        self._store = store
        self._capacity = capacity

    def bind(self, store: StateStore) -> None:
        if self._store is not None:
            raise RuntimeError("Mimir catalog review state store is already bound")
        self._store = store

    async def retain(
        self,
        candidate: Mapping[str, Any],
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt | None:
        """Create one restart-safe pending record and verify independent readback."""
        store = self._store
        if store is None:
            return None
        candidate_key = journal_idempotency_key(candidate)
        key = state_key(candidate_key)
        value = {
            "kind": RECORD_KIND,
            "revision": 1,
            "status": "pending",
            "idempotency_key": candidate_key,
            "candidate_digest": package.candidate.digest,
            "package_digest": package.content_digest,
            "candidate": dict(candidate),
        }
        created = await store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "mimir_catalog_review_pending",
                "principal": "Mimir",
                "idempotency_key": candidate_key,
                "candidate_digest": package.candidate.digest,
                "package_digest": package.content_digest,
                "grants_authority": False,
            },
        )
        readback = await store.read_state(key)
        if readback is None:
            raise RuntimeError("Mimir catalog review pending record is unavailable")
        validate_identity(
            readback,
            candidate=candidate,
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
        )
        if created or readback.get("status") == "pending":
            return None
        if readback.get("status") == "published":
            review_ref = readback.get("review_ref")
            if not isinstance(review_ref, str):
                raise ValueError("Mimir catalog review publication reference is invalid")
            return CatalogReviewPublicationReceipt(
                package_digest=package.content_digest,
                review_ref=review_ref,
                already_existed=True,
            )
        if readback.get("status") in _TERMINAL_STATUSES:
            raise ValueError("Mimir catalog review candidate is already terminal")
        raise ValueError("Mimir catalog review durable status is invalid")

    async def pending_candidates(self) -> tuple[tuple[dict[str, Any], ...], int]:
        store = self._store
        if store is None:
            return (), 0
        rows, total = await store.read_state_page(
            f"{STATE_PREFIX}/",
            limit=self._capacity,
            field="status",
            value="pending",
        )
        pending: list[dict[str, Any]] = []
        for row in rows:
            if row.get("kind") != RECORD_KIND:
                raise ValueError("Mimir catalog review durable record has invalid kind")
            if row.get("status") != "pending":
                continue
            candidate = row.get("candidate")
            if not isinstance(candidate, Mapping):
                raise ValueError("Mimir catalog review pending candidate is invalid")
            validate_identity(
                row,
                candidate=candidate,
                candidate_digest=required_digest(row, "candidate_digest"),
                package_digest=required_digest(row, "package_digest"),
            )
            pending.append(dict(candidate))
        return tuple(pending), total

    async def publication_receipt(
        self,
        candidate: Mapping[str, Any],
        *,
        candidate_digest: str,
    ) -> CatalogReviewPublicationReceipt | None:
        """Return a matching durable publication before applying pending capacity."""
        store = self._store
        if store is None:
            return None
        current = await store.read_state(state_key(journal_idempotency_key(candidate)))
        if current is None or current.get("status") == "pending":
            return None
        if (
            current.get("kind") != RECORD_KIND
            or current.get("idempotency_key") != journal_idempotency_key(candidate)
            or required_digest(current, "candidate_digest") != candidate_digest
        ):
            raise ValueError("Mimir catalog review durable identity conflict")
        if current.get("status") != "published":
            raise ValueError("Mimir catalog review candidate is already terminal")
        review_ref = current.get("review_ref")
        if not isinstance(review_ref, str):
            raise ValueError("Mimir catalog review publication reference is invalid")
        return CatalogReviewPublicationReceipt(
            package_digest=required_digest(current, "package_digest"),
            review_ref=review_ref,
            already_existed=True,
        )

    async def pending_identity(
        self,
        candidate: Mapping[str, Any],
        *,
        candidate_digest: str | None = None,
    ) -> tuple[str, str] | None:
        """Return exact pending digests while rejecting retained candidate tampering."""
        store = self._store
        if store is None:
            return None
        current = await store.read_state(state_key(journal_idempotency_key(candidate)))
        if current is None or current.get("status") != "pending":
            return None
        stored_candidate_digest = required_digest(current, "candidate_digest")
        package_digest = required_digest(current, "package_digest")
        validate_identity(
            current,
            candidate=candidate,
            candidate_digest=stored_candidate_digest,
            package_digest=package_digest,
        )
        if candidate_digest is not None and stored_candidate_digest != candidate_digest:
            raise ValueError("Mimir catalog review durable candidate conflict")
        return stored_candidate_digest, package_digest

    async def mark_published(
        self,
        candidate: Mapping[str, Any],
        package: CatalogReviewPackage,
        receipt: CatalogReviewPublicationReceipt,
    ) -> None:
        """Replace one pending candidate with content-free publication lineage."""
        await self._mark_terminal(
            candidate,
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
            status="published",
            reason="catalog_review_published",
            review_ref=receipt.review_ref,
        )

    async def invalidate(
        self,
        candidate: Mapping[str, Any],
        *,
        reason: str,
    ) -> None:
        """Remove pending case references after current-source admission fails."""
        store = self._store
        if store is None:
            return
        current = await store.read_state(state_key(journal_idempotency_key(candidate)))
        if current is None:
            return
        await self._mark_terminal(
            candidate,
            candidate_digest=required_digest(current, "candidate_digest"),
            package_digest=required_digest(current, "package_digest"),
            status="invalidated",
            reason=reason,
            review_ref=None,
        )

    async def _mark_terminal(
        self,
        candidate: Mapping[str, Any],
        *,
        candidate_digest: str,
        package_digest: str,
        status: str,
        reason: str,
        review_ref: str | None,
    ) -> None:
        store = self._store
        if store is None:
            return
        candidate_key = journal_idempotency_key(candidate)
        key = state_key(candidate_key)
        current = await store.read_state(key)
        if current is None:
            raise RuntimeError("Mimir catalog review pending record is unavailable")
        validate_identity(
            current,
            candidate=candidate,
            candidate_digest=candidate_digest,
            package_digest=package_digest,
        )
        if current.get("status") == status:
            return
        if current.get("status") != "pending":
            raise ValueError("Mimir catalog review terminal state conflict")
        revision = current.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("Mimir catalog review revision is invalid")
        terminal = {
            "kind": RECORD_KIND,
            "revision": revision + 1,
            "status": status,
            "idempotency_key": candidate_key,
            "candidate_digest": candidate_digest,
            "package_digest": package_digest,
            "reason": reason,
            **({"review_ref": review_ref} if review_ref is not None else {}),
        }
        if not await store.compare_and_set_state_with_audit(
            key,
            terminal,
            expected_revision=revision,
            audit_entry={
                "kind": f"mimir_catalog_review_{status}",
                "principal": "Mimir",
                "idempotency_key": candidate_key,
                "candidate_digest": candidate_digest,
                "package_digest": package_digest,
                "reason": reason,
                "grants_authority": False,
            },
        ):
            raise RuntimeError("Mimir catalog review terminal CAS failed")
        readback = await store.read_state(key)
        if readback != terminal:
            raise RuntimeError("Mimir catalog review terminal readback failed")
        await store.delete_states_beyond(
            f"{STATE_PREFIX}/",
            retain_newest=self._capacity + _TERMINAL_RECEIPT_RETAIN,
        )


__all__ = ["MimirCatalogReviewJournal"]
