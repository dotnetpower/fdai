from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.mimir_candidate_quarantine import quarantine_candidate
from fdai.agents._framework.mimir_catalog_journal import MimirCatalogReviewJournal
from fdai.agents._framework.mimir_governance_state import (
    CatalogReviewCapacityError,
    CatalogReviewPublicationError,
    MimirCatalogGovernanceStore,
    catalog_candidate_idempotency_key,
)
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCompilationError,
    CatalogReviewOutcome,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogReviewPublisher,
)
from fdai.shared.providers.state_store import StateStore


class MimirCatalogReviewMixin:
    bus: PantheonBus | None
    _catalog_candidate_compiler: CatalogCandidateCompiler | None
    _catalog_review_journal: MimirCatalogReviewJournal
    _catalog_review_packages: dict[str, CatalogReviewPackage]
    _catalog_review_publisher: CatalogReviewPublisher | None
    _guard: CandidateGuard
    _investigation_candidates: BoundedLruDict[str, str]
    _package_by_idempotency: dict[str, str]
    _pending_candidates: deque[dict[str, Any]]
    _operational_pending_targets: BoundedLruSet[str]
    _catalog_draft_rule_ids: BoundedLruSet[str]
    _published_operational_targets: BoundedLruSet[str]
    _published_reviews: BoundedLruDict[str, tuple[str, str, CatalogReviewPublicationReceipt]]
    _quarantined_candidates: deque[dict[str, Any]]
    _max_pending_candidates: int
    _max_review_packages: int

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
        if require_topic_owner(
            self,
            "object.rule-candidate",
            payload,
            behavior="catalog_candidate:invalid_producer",
        ):
            await quarantine_candidate(self, payload, "invalid_producer")
            return
        if payload.get("source_signal") == "investigation_strategy_comparison_cohort":
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
            await quarantine_candidate(self, payload, verdict.reason)

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
            target = str(candidate.get("target_rule_id") or "")
            if target:
                self._operational_pending_targets.add(target)
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
        draft_rule_id = _package_draft_rule_id(package)
        if draft_rule_id:
            self._catalog_draft_rule_ids.add(draft_rule_id)
        target = str(candidate.get("target_rule_id") or "")
        if target:
            self._operational_pending_targets.add(target)
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
        mark_task = asyncio.gather(
            *(
                self._catalog_review_journal.mark_published(completed_candidate, package, receipt)
                for completed_candidate in self._package_candidates(candidate, package)
            )
        )
        try:
            await asyncio.shield(mark_task)
        except asyncio.CancelledError:
            await mark_task
            raise
        await self._audit_outcome(
            candidate,
            outcome="published",
            reason=("existing_review" if receipt.already_existed else "new_review"),
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
            review_ref=receipt.review_ref,
        )
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
        self._catalog_draft_rule_ids = BoundedLruSet(self._max_review_packages)
        for retained in self._catalog_review_packages.values():
            draft_rule_id = _package_draft_rule_id(retained)
            if draft_rule_id:
                self._catalog_draft_rule_ids.add(draft_rule_id)
        self._pending_candidates = deque(
            item
            for item in self._pending_candidates
            if item.get("idempotency_key") not in completed_keys
        )
        self._operational_pending_targets = BoundedLruSet(self._max_pending_candidates)
        for item in self._pending_candidates:
            if item.get("source_signal") == "operational_case_fingerprint_cohort":
                target = str(item.get("target_rule_id") or "")
                if target:
                    self._operational_pending_targets.add(target)

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
            self.record_behavior("catalog_review_audit_unavailable")
            return
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


def _package_draft_rule_id(package: CatalogReviewPackage) -> str:
    draft_rule = getattr(package, "draft_rule", None)
    mapping = getattr(draft_rule, "mapping", None)
    if not isinstance(mapping, Mapping):
        return ""
    value = mapping.get("id")
    return value if isinstance(value, str) else ""
