"""Durable pending-work journal for Mimir operational catalog reviews."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.mimir_catalog_identity import (
    RECORD_KIND,
    STATE_PREFIX,
    required_digest,
    state_key,
    validate_identity,
)
from fdai.agents._framework.mimir_catalog_identity import (
    idempotency_key as journal_idempotency_key,
)
from fdai.agents._framework.mimir_governance_state import (
    CatalogReviewCapacityError,
    CatalogReviewPublicationError,
    MimirCatalogGovernanceStore,
    catalog_candidate_idempotency_key,
)
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCompilationError,
    CatalogReviewOutcome,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogReviewPublisher,
)
from fdai.shared.providers.state_store import StateStore

_TERMINAL_STATUSES = frozenset({"invalidated", "published"})


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
        await store.compare_and_set_state_with_audit(
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
        )
        readback = await store.read_state(key)
        if readback != terminal:
            raise RuntimeError("Mimir catalog review terminal readback failed")


class MimirCatalogReviewMixin:
    bus: PantheonBus | None
    _catalog_candidate_compiler: CatalogCandidateCompiler | None
    _catalog_review_journal: MimirCatalogReviewJournal
    _catalog_review_packages: dict[str, CatalogReviewPackage]
    _catalog_review_publisher: CatalogReviewPublisher | None
    _guard: CandidateGuard
    _investigation_candidates: BoundedLruDict[str, str]
    _max_pending_candidates: int
    _max_review_packages: int
    _package_by_idempotency: dict[str, str]
    _pending_candidates: deque[dict[str, Any]]
    _published_operational_targets: BoundedLruSet[str]
    _published_reviews: BoundedLruDict[
        str,
        tuple[str, str, CatalogReviewPublicationReceipt],
    ]
    _quarantined_candidates: deque[dict[str, Any]]

    async def _require_current_candidate_cases(self, candidate: dict[str, Any]) -> None:
        raise NotImplementedError

    def record_behavior(self, key: str, count: int = 1) -> None:
        raise NotImplementedError

    def _init_catalog_review(
        self,
        *,
        compiler: CatalogCandidateCompiler | None,
        publisher: CatalogReviewPublisher | None,
        state_store: StateStore | None,
        max_pending_candidates: int,
        max_review_packages: int,
        max_quarantine: int,
    ) -> None:
        self._pending_candidates = deque()
        self._quarantined_candidates = deque(maxlen=max_quarantine)
        self._guard = CandidateGuard()
        self._catalog_candidate_compiler = compiler
        self._catalog_review_publisher = publisher
        self._catalog_review_journal = MimirCatalogReviewJournal(
            state_store, capacity=max_review_packages
        )
        self._catalog_governance_store = MimirCatalogGovernanceStore(state_store)
        self._max_pending_candidates = max_pending_candidates
        self._max_review_packages = max_review_packages
        self._catalog_review_packages = {}
        self._package_by_idempotency = {}
        self._published_reviews = BoundedLruDict(max_review_packages)
        self._published_operational_targets = BoundedLruSet(max_review_packages)
        self._investigation_candidates = BoundedLruDict(max_pending_candidates)

    def bind_catalog_review_state_store(self, store: StateStore) -> None:
        self._catalog_review_journal.bind(store)
        self._catalog_governance_store.bind(store)

    async def _handle_rule_candidate(
        self,
        payload: dict[str, Any],
        *,
        recovering: bool = False,
    ) -> None:
        investigation_identity: tuple[str, str] | None = None
        if payload.get("source_signal") == "investigation_strategy_comparison_cohort":
            if payload.get("producer_principal") != "Norns":
                raise ValueError("investigation strategy candidate MUST be published by Norns")
            idempotency_key = str(payload.get("idempotency_key") or "")
            evidence = payload.get("evidence")
            candidate_digest = (
                str(evidence.get("candidate_digest") or "") if isinstance(evidence, dict) else ""
            )
            if not idempotency_key or not candidate_digest:
                raise ValueError("investigation strategy candidate identity is missing")
            existing = self._investigation_candidates.get(idempotency_key)
            if existing is not None:
                if existing != candidate_digest:
                    raise ValueError("investigation strategy candidate idempotency conflict")
                self.record_behavior("investigation_strategy_candidate_duplicate")
                return
            durable_existing = await self._catalog_governance_store.investigation_candidate(
                idempotency_key
            )
            if durable_existing is not None:
                if durable_existing != candidate_digest:
                    raise ValueError("investigation strategy candidate idempotency conflict")
                self._investigation_candidates.set(idempotency_key, candidate_digest)
                self.record_behavior("investigation_strategy_candidate_duplicate")
                return
            investigation_identity = (idempotency_key, candidate_digest)
        if payload.get("source_signal") == "operational_case_fingerprint_cohort":
            idempotency_key = self._idempotency_key(payload)
            if (
                idempotency_key in self._package_by_idempotency
                or idempotency_key in self._published_reviews
            ):
                await self._retry_operational_candidate(payload)
                return
        verdict = self._guard.inspect(payload)
        if verdict.accepted:
            await self._accept_candidate(payload, recovering=recovering)
            if investigation_identity is not None:
                self._investigation_candidates.set(*investigation_identity)
                await self._catalog_governance_store.persist_investigation_candidate(
                    *investigation_identity
                )
        else:
            prior_quarantine = await self._catalog_governance_store.quarantine(payload)
            if prior_quarantine is not None:
                self._quarantined_candidates.append(prior_quarantine)
                self.record_behavior("catalog_candidate_quarantine_duplicate")
                return
            self._quarantined_candidates.append(
                {**dict(payload), "quarantine_reason": verdict.reason}
            )
            await self._catalog_governance_store.persist_quarantine(payload, verdict.reason)
            await self._audit_outcome(payload, outcome="quarantined", reason=verdict.reason)

    async def recover_catalog_reviews(self) -> int:
        candidates, total = await self._catalog_review_journal.pending_candidates()
        for candidate in candidates:
            try:
                await self._handle_rule_candidate(candidate, recovering=True)
            except PermissionError:
                await self._catalog_review_journal.invalidate(
                    candidate, reason="source_no_longer_current"
                )
                await self._audit_outcome(
                    candidate,
                    outcome="invalidated",
                    reason="source_no_longer_current",
                )
                self.record_behavior("operational_catalog_source_invalidated")
            except CatalogReviewPublicationError:
                self.record_behavior("operational_catalog_publication_retry_pending")
        if total > len(candidates):
            self.record_behavior(
                "operational_catalog_recovery_deferred",
                total - len(candidates),
            )
        return len(candidates)

    async def _accept_candidate(
        self,
        payload: dict[str, Any],
        *,
        recovering: bool,
    ) -> None:
        candidate = dict(payload)
        if candidate.get("source_signal") != "operational_case_fingerprint_cohort":
            self._ensure_pending_capacity()
            self._pending_candidates.append(candidate)
            return
        compiler = self._catalog_candidate_compiler
        if compiler is None:
            await self._require_current_candidate_cases(candidate)
            self._ensure_pending_capacity()
            self._pending_candidates.append(candidate)
            self.record_behavior("operational_catalog_compiler_unavailable")
            return
        if recovering:
            await self._require_current_candidate_cases(candidate)
        try:
            package = compiler.compile(candidate)
        except CatalogCompilationError as exc:
            pending_identity = await self._catalog_review_journal.pending_identity(
                candidate,
            )
            if pending_identity is not None:
                candidate_digest, package_digest = pending_identity
                await self._catalog_review_journal.invalidate(
                    candidate, reason=f"recompile_failed:{exc.code}"
                )
                await self._audit_outcome(
                    candidate,
                    outcome="invalidated",
                    reason=f"recompile_failed:{exc.code}",
                    candidate_digest=candidate_digest,
                    package_digest=package_digest,
                )
                self.record_behavior("operational_catalog_recompile_invalidated")
                return
            self._quarantined_candidates.append(
                {**candidate, "quarantine_reason": f"catalog_compile:{exc.code}"}
            )
            self.record_behavior("operational_catalog_compile_failed")
            await self._audit_outcome(
                candidate,
                outcome="quarantined",
                reason=f"catalog_compile:{exc.code}",
            )
            return
        if not recovering:
            await self._require_current_candidate_cases(candidate)
        published = await self._catalog_review_journal.publication_receipt(
            candidate,
            candidate_digest=package.candidate.digest,
        )
        if published is not None:
            await self._audit_outcome(
                candidate,
                outcome="duplicate",
                reason="publication_already_recorded",
                candidate_digest=package.candidate.digest,
                package_digest=published.package_digest,
                review_ref=published.review_ref,
            )
            self._remember_published(candidate, package.candidate.digest, published)
            return
        pending_identity = await self._catalog_review_journal.pending_identity(
            candidate,
            candidate_digest=package.candidate.digest,
        )
        if pending_identity is not None and pending_identity[1] != package.content_digest:
            await self._catalog_review_journal.invalidate(
                candidate, reason="compilation_identity_changed"
            )
            await self._audit_outcome(
                candidate,
                outcome="invalidated",
                reason="compilation_identity_changed",
                candidate_digest=pending_identity[0],
                package_digest=pending_identity[1],
            )
            self.record_behavior("operational_catalog_compilation_changed")
            return
        if (
            package.content_digest not in self._catalog_review_packages
            and len(self._catalog_review_packages) >= self._max_review_packages
        ):
            raise CatalogReviewCapacityError("Mimir catalog review package capacity exhausted")
        self._ensure_pending_capacity()
        published = await self._catalog_review_journal.retain(candidate, package)
        if published is not None:
            await self._audit_outcome(
                candidate,
                outcome="duplicate",
                reason="publication_already_recorded",
                candidate_digest=package.candidate.digest,
                package_digest=published.package_digest,
                review_ref=published.review_ref,
            )
            self._remember_published(candidate, package.candidate.digest, published)
            return
        self._pending_candidates.append(candidate)
        self._catalog_review_packages[package.content_digest] = package
        self._package_by_idempotency[self._idempotency_key(candidate)] = package.content_digest
        await self._publish_package(candidate, package)
        self.record_behavior("operational_catalog_review_ready")

    async def _retry_operational_candidate(self, payload: dict[str, Any]) -> None:
        compiler = self._catalog_candidate_compiler
        if compiler is None:
            raise RuntimeError("retained operational package has no compiler")
        candidate = dict(payload)
        package = compiler.compile(candidate)
        try:
            await self._require_current_candidate_cases(candidate)
        except PermissionError:
            await self._invalidate_package(candidate, package)
            return
        idempotency_key = self._idempotency_key(candidate)
        published = self._published_reviews.get(idempotency_key)
        if published is not None:
            candidate_digest, package_digest, receipt = published
            if package.content_digest != package_digest:
                await self._audit_outcome(
                    candidate,
                    outcome="conflict",
                    reason="idempotency_payload_conflict",
                    candidate_digest=package.candidate.digest,
                    package_digest=package.content_digest,
                )
                raise ValueError("catalog review idempotency payload conflict")
            await self._audit_outcome(
                candidate,
                outcome="duplicate",
                reason="publication_already_recorded",
                candidate_digest=candidate_digest,
                package_digest=package_digest,
                review_ref=receipt.review_ref,
            )
            return
        retained_digest = self._package_by_idempotency[idempotency_key]
        if package.content_digest != retained_digest:
            await self._audit_outcome(
                candidate,
                outcome="conflict",
                reason="idempotency_payload_conflict",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise ValueError("catalog review idempotency payload conflict")
        await self._publish_package(candidate, self._catalog_review_packages[retained_digest])

    async def _publish_package(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
    ) -> None:
        try:
            await self._require_current_candidate_cases(candidate)
        except PermissionError:
            await self._invalidate_package(candidate, package)
            return
        publisher = self._catalog_review_publisher
        if publisher is None:
            await self._audit_outcome(
                candidate,
                outcome="retained",
                reason="publisher_unavailable",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            return
        try:
            receipt = await publisher.publish(package)
        except Exception as exc:
            await self._audit_outcome(
                candidate,
                outcome="publication_failed",
                reason=f"publisher_error:{type(exc).__name__}",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise CatalogReviewPublicationError("catalog review publisher unavailable") from exc
        if (
            not isinstance(receipt, CatalogReviewPublicationReceipt)
            or receipt.package_digest != package.content_digest
        ):
            await self._audit_outcome(
                candidate,
                outcome="publication_failed",
                reason="receipt_digest_conflict",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise ValueError("catalog review publication receipt digest conflict")
        await self._audit_outcome(
            candidate,
            outcome="published",
            reason=("existing_review" if receipt.already_existed else "new_review"),
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
            review_ref=receipt.review_ref,
        )
        for completed_candidate in self._package_candidates(candidate, package):
            await self._catalog_review_journal.mark_published(completed_candidate, package, receipt)
        self._complete_publication(candidate, package, receipt)

    async def _invalidate_package(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
    ) -> None:
        for invalidated_candidate in self._package_candidates(candidate, package):
            await self._catalog_review_journal.invalidate(
                invalidated_candidate, reason="source_no_longer_current"
            )
        await self._audit_outcome(
            candidate,
            outcome="invalidated",
            reason="source_no_longer_current",
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
        )
        self._discard_package(candidate, package)
        self.record_behavior("operational_catalog_source_invalidated")

    def _package_candidates(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
    ) -> tuple[dict[str, Any], ...]:
        by_idempotency = {
            self._idempotency_key(item): item
            for item in self._pending_candidates
            if self._package_by_idempotency.get(self._idempotency_key(item))
            == package.content_digest
        }
        by_idempotency[self._idempotency_key(candidate)] = candidate
        return tuple(by_idempotency.values())

    def _complete_publication(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
        receipt: CatalogReviewPublicationReceipt,
    ) -> None:
        completed_keys = {
            idempotency_key
            for idempotency_key, package_digest in self._package_by_idempotency.items()
            if package_digest == package.content_digest
        }
        completed_keys.add(self._idempotency_key(candidate))
        for idempotency_key in completed_keys:
            completed_candidate = next(
                (
                    item
                    for item in self._pending_candidates
                    if self._idempotency_key(item) == idempotency_key
                ),
                candidate,
            )
            self._remember_published(
                completed_candidate,
                package.candidate.digest,
                receipt,
            )
        self._discard_package(candidate, package)

    def _remember_published(
        self,
        candidate: Mapping[str, Any],
        candidate_digest: str,
        receipt: CatalogReviewPublicationReceipt,
    ) -> None:
        self._published_reviews.set(
            self._idempotency_key(candidate),
            (candidate_digest, receipt.package_digest, receipt),
        )
        target_rule_id = str(candidate.get("target_rule_id") or "")
        if target_rule_id:
            self._published_operational_targets.add(target_rule_id)

    def _discard_package(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
    ) -> None:
        completed_keys = {
            idempotency_key
            for idempotency_key, package_digest in self._package_by_idempotency.items()
            if package_digest == package.content_digest
        }
        completed_keys.add(self._idempotency_key(candidate))
        for idempotency_key in completed_keys:
            self._package_by_idempotency.pop(idempotency_key, None)
        self._catalog_review_packages.pop(package.content_digest, None)
        self._pending_candidates = deque(
            item
            for item in self._pending_candidates
            if item.get("idempotency_key") not in completed_keys
        )

    def _ensure_pending_capacity(self) -> None:
        if len(self._pending_candidates) >= self._max_pending_candidates:
            raise CatalogReviewCapacityError("Mimir pending candidate capacity exhausted")

    _idempotency_key = staticmethod(catalog_candidate_idempotency_key)

    async def _audit_outcome(
        self,
        payload: dict[str, Any],
        *,
        outcome: str,
        reason: str,
        candidate_digest: str | None = None,
        package_digest: str | None = None,
        review_ref: str | None = None,
    ) -> None:
        correlation = payload.get("correlation_id")
        record = CatalogReviewOutcome(
            idempotency_key=self._idempotency_key(payload),
            correlation_id=(
                correlation if isinstance(correlation, str) and correlation else "unavailable"
            ),
            candidate_digest=candidate_digest,
            package_digest=package_digest,
            outcome=outcome,
            reason=reason,
            review_ref=review_ref,
        )
        if self.bus is None:
            raise RuntimeError("Mimir catalog review audit transport is unavailable")
        await self.bus.publish(
            "Mimir",
            "object.rule",
            {
                "kind": "catalog_review_outcome",
                "correlation_id": record.correlation_id,
                "idempotency_key": record.idempotency_key,
                "candidate_digest": record.candidate_digest,
                "package_digest": record.package_digest,
                "outcome": record.outcome,
                "reason": record.reason,
                "review_ref": record.review_ref,
                "mode": "shadow",
            },
        )

    def pending_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._pending_candidates)

    def quarantined_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._quarantined_candidates)

    def catalog_review_packages(self) -> tuple[CatalogReviewPackage, ...]:
        return tuple(self._catalog_review_packages.values())

    def catalog_review_publication_receipts(
        self,
    ) -> tuple[CatalogReviewPublicationReceipt, ...]:
        return tuple(item[2] for _, item in self._published_reviews.items())


__all__ = [
    "CatalogReviewCapacityError",
    "CatalogReviewPublicationError",
    "MimirCatalogReviewJournal",
    "MimirCatalogReviewMixin",
]
