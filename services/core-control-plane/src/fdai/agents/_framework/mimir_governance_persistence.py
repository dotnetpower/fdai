"""Mimir - Rule Steward (Wave 2 behavior).

Mimir tracks rule shadow / enforce promotion. Wave 2 exposes a minimal
in-memory promotion tracker; the concrete rule catalog loader stays in
:mod:`fdai.rule_catalog`. Mimir's job here is the promotion state
machine and the RuleCandidate intake.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
)
from fdai.agents._framework.topics import stable_idempotency_key

#: Cap on retained rejected-candidate records. Quarantine holds candidates the
#: CandidateGuard REJECTED - i.e. attacker-controlled volume under a
#: candidate-poisoning attempt. An unbounded list would be a memory-exhaustion
#: DoS vector: a poisoning flood grows it without limit. The durable audit
#: trail is Saga's chain; this in-memory list is a bounded diagnostic ring.
_MAX_QUARANTINE = 5_000
_MAX_PENDING_CANDIDATES = 5_000
_MAX_CATALOG_REVIEW_PACKAGES = 5_000
_MAX_ISSUE_FINGERPRINTS = 50_000
_GOVERNANCE_RECOVERY_PAGE = 128
_RULE_GENERATION_RECEIPT_RETAIN = 5_000
_MAX_PROMOTION_PERSIST_QUEUE = 1_024
_MAX_PROMOTION_PERSIST_ATTEMPTS = 8
_RULE_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)
_RULE_PUBLICATION_MAINTENANCE_PAGE = 16
_MAX_MAINTENANCE_RECORDS = 128
_OPERATIONAL_RULE_PREFIX = "learned.operational."
_RULE_GENERATION_RECEIPT_PREFIX = "mimir:rule-generation-activation-result:"
_RULE_GENERATION_VALIDATION_PREFIX = "mimir:rule-generation-validation-result:"
_RULE_GENERATION_COMMAND_PREFIX = "mimir:rule-generation-activation-command:"
_GOVERNANCE_PREFIX = "pantheon/mimir/governance"
_RULE_STATE_PREFIX = f"{_GOVERNANCE_PREFIX}/rules"
_ISSUE_FINGERPRINT_PREFIX = f"{_GOVERNANCE_PREFIX}/issue-fingerprints"
_RULE_PUBLICATION_PREFIX = f"{_GOVERNANCE_PREFIX}/rule-publications"
_DEPRECATION_CANDIDATE_PREFIX = f"{_GOVERNANCE_PREFIX}/deprecation-candidates"
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0
_REVIEWED_REPOSITORY_PREFIX = re.compile(
    r"^https://(?P<host>[A-Za-z0-9.-]{1,253})/"
    r"(?P<owner>[A-Za-z0-9_.-]{1,100})/"
    r"(?P<repo>[A-Za-z0-9_.-]{1,100})$"
)
_REVIEWED_CATALOG_PR_REF = re.compile(
    r"^catalog-pr:(?P<repository>https://[A-Za-z0-9.-]{1,253}/"
    r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})/"
    r"pull/[1-9][0-9]{0,18}@sha256:"
    r"(?P<digest>[a-f0-9]{64})$"
)
_REVIEWED_CATALOG_COMMIT_REF = re.compile(
    r"^catalog-commit:[a-f0-9]{40}@sha256:(?P<digest>[a-f0-9]{64})$"
)


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


def _rule_state_key(rule_id: str) -> str:
    return f"{_RULE_STATE_PREFIX}/{rule_id}"


def _issue_fingerprint_key(fingerprint: str) -> str:
    return f"{_ISSUE_FINGERPRINT_PREFIX}/{fingerprint}"


def _rule_publication_key(idempotency_key: str) -> str:
    return f"{_RULE_PUBLICATION_PREFIX}/{idempotency_key}"


def _issue_close_evidence_idempotency_key(outcome: MimirCatalogPromotionOutcome) -> str:
    return stable_idempotency_key(
        "mimir-issue-close-promotion-evidence",
        outcome.problem_fingerprint,
        outcome.promotion_pr,
        outcome.correlation_id,
    )


def _reviewed_package_digest(
    reviewed_change_ref: str | None,
    *,
    allowed_repository_prefixes: frozenset[str] = frozenset(),
) -> str | None:
    if reviewed_change_ref is None:
        return None
    candidate = reviewed_change_ref.strip()
    pr_match = _REVIEWED_CATALOG_PR_REF.fullmatch(candidate)
    if pr_match is not None:
        repository = _normalize_reviewed_repository_prefix(pr_match.group("repository"))
        if repository is None:
            return None
        if allowed_repository_prefixes and repository not in allowed_repository_prefixes:
            return None
        return pr_match.group("digest")
    commit_match = _REVIEWED_CATALOG_COMMIT_REF.fullmatch(candidate)
    if commit_match is not None:
        return commit_match.group("digest")
    return None


def _normalize_reviewed_repository_prefix(prefix: str) -> str | None:
    match = _REVIEWED_REPOSITORY_PREFIX.fullmatch(prefix.strip())
    if match is None:
        return None
    host = match.group("host").lower()
    if not _valid_review_host(host):
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    if owner in {".", ".."} or repo in {".", ".."}:
        return None
    return f"https://{host}/{owner}/{repo}"


def _normalize_reviewed_repository_prefixes(prefixes: Sequence[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for prefix in prefixes:
        value = _normalize_reviewed_repository_prefix(prefix)
        if value is None:
            raise ValueError("Mimir reviewed repository prefix MUST be a structural HTTPS repo URL")
        normalized.add(value)
    return frozenset(normalized)


def _valid_review_host(host: str) -> bool:
    if len(host) > 253 or "." not in host:
        return False
    labels = host.split(".")
    return all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is not None
        for label in labels
    )


def _run_coroutine_blocking(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # noqa: BLE001 - re-raise in caller thread
            result["error"] = exc

    thread = threading.Thread(target=runner, name="mimir-promotion-sync")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _promotion_topic(rule_id: str, source: str) -> str:
    if rule_id.startswith("policy.") or source == "policy":
        return "object.policy"
    return "object.rule"


class MimirGovernancePersistenceMixin:
    """Behavior-preserving extracted runtime methods."""

    _promotion_persist_worker: asyncio.Task[None] | None

    async def drain_governance_writes(self: Any) -> None:
        """Wait for sync promotion/revocation persistence tasks before restart tests."""
        while self._promotion_persist_tasks:
            await asyncio.gather(*tuple(self._promotion_persist_tasks))
        worker = self._promotion_persist_worker
        if worker is not None:
            await worker

    def _persist_promotion(self: Any, promotion: RulePromotion) -> None:
        store = self._governance_state_store
        if store is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._persist_promotion_record(promotion))
            return
        if (
            promotion.rule_id not in self._promotion_persist_pending
            and len(self._promotion_persist_pending) >= _MAX_PROMOTION_PERSIST_QUEUE
        ):
            self.record_behavior("promotion:persist_backpressure")
            raise RuntimeError("Mimir promotion persistence queue is full")
        self._promotion_persist_pending[promotion.rule_id] = promotion
        if self._promotion_persist_worker is None or self._promotion_persist_worker.done():
            self._promotion_persist_worker = loop.create_task(self._drain_promotion_persist_queue())
            self._promotion_persist_tasks.add(self._promotion_persist_worker)
            self._promotion_persist_worker.add_done_callback(self._promotion_persist_done)

    def _promotion_persist_done(self: Any, task: asyncio.Task[None]) -> None:
        self._promotion_persist_tasks.discard(task)
        if self._promotion_persist_worker is task:
            self._promotion_persist_worker = None
        try:
            task.result()
        except Exception:
            self.record_behavior("promotion:persist_failed")

    async def _drain_promotion_persist_queue(self: Any) -> None:
        while self._promotion_persist_pending:
            _rule_id, promotion = self._promotion_persist_pending.popitem()
            await self._persist_promotion_record(promotion)

    async def _persist_promotion_record(self: Any, promotion: RulePromotion) -> None:
        store = self._governance_state_store
        if store is None:
            return
        key = _rule_state_key(promotion.rule_id)
        for attempt in range(_MAX_PROMOTION_PERSIST_ATTEMPTS):
            current = await store.read_state(key)
            revision = int(current.get("revision", 0)) if current is not None else 0
            record = {
                "kind": "mimir_rule_state",
                "revision": revision + 1,
                "rule_id": promotion.rule_id,
                "state": promotion.state,
                "source": promotion.source,
                "updated_at": promotion.updated_at,
                "terminal": promotion.state == "retired",
            }
            audit = {
                "kind": "mimir_rule_state_recorded",
                "principal": "Mimir",
                "rule_id": promotion.rule_id,
                "state": promotion.state,
                "revision": revision + 1,
                "grants_authority": False,
            }
            if current is None:
                if await store.write_state_with_audit_if_absent(key, record, audit):
                    return
            elif await store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=audit,
            ):
                return
            self.record_behavior("promotion:persist_cas_retry")
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        self.record_behavior("promotion:persist_cas_exhausted")
        raise RuntimeError("Mimir promotion persistence CAS did not converge")

    async def _persist_issue_fingerprint(self: Any, record: dict[str, Any]) -> None:
        store = self._governance_state_store
        if store is None:
            return
        fingerprint = str(record["fingerprint"])
        key = _issue_fingerprint_key(fingerprint)
        current = await store.read_state(key)
        revision = int(current.get("revision", 0)) if current is not None else 0
        value = {
            "kind": "mimir_issue_fingerprint",
            "revision": revision + 1,
            **record,
        }
        audit = {
            "kind": "mimir_issue_fingerprint_recorded",
            "principal": "Mimir",
            "fingerprint": fingerprint,
            "issue_number": record["issue_number"],
            "revision": revision + 1,
            "grants_authority": False,
        }
        if current is None:
            await store.write_state_with_audit_if_absent(key, value, audit)
            return
        await store.compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )


__all__ = ["MimirGovernancePersistenceMixin"]
