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
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.mimir_constants import (
    _DEFAULT_PROVIDER_TIMEOUT_SECONDS as _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
)
from fdai.agents._framework.mimir_constants import (
    _DEPRECATION_CANDIDATE_PREFIX as _DEPRECATION_CANDIDATE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _GOVERNANCE_PREFIX as _GOVERNANCE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _GOVERNANCE_RECOVERY_PAGE as _GOVERNANCE_RECOVERY_PAGE,
)
from fdai.agents._framework.mimir_constants import (
    _ISSUE_FINGERPRINT_PREFIX as _ISSUE_FINGERPRINT_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_CATALOG_REVIEW_PACKAGES as _MAX_CATALOG_REVIEW_PACKAGES,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_ISSUE_FINGERPRINTS as _MAX_ISSUE_FINGERPRINTS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_MAINTENANCE_RECORDS as _MAX_MAINTENANCE_RECORDS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PENDING_CANDIDATES as _MAX_PENDING_CANDIDATES,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PROMOTION_PERSIST_ATTEMPTS as _MAX_PROMOTION_PERSIST_ATTEMPTS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PROMOTION_PERSIST_QUEUE as _MAX_PROMOTION_PERSIST_QUEUE,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_QUARANTINE as _MAX_QUARANTINE,
)
from fdai.agents._framework.mimir_constants import (
    _OPERATIONAL_RULE_PREFIX as _OPERATIONAL_RULE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_CATALOG_COMMIT_REF as _REVIEWED_CATALOG_COMMIT_REF,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_CATALOG_PR_REF as _REVIEWED_CATALOG_PR_REF,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_REPOSITORY_PREFIX as _REVIEWED_REPOSITORY_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_COMMAND_PREFIX as _RULE_GENERATION_COMMAND_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_RECEIPT_PREFIX as _RULE_GENERATION_RECEIPT_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_RECEIPT_RETAIN as _RULE_GENERATION_RECEIPT_RETAIN,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_VALIDATION_PREFIX as _RULE_GENERATION_VALIDATION_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_CLAIM_LEASE as _RULE_PUBLICATION_CLAIM_LEASE,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_MAINTENANCE_PAGE as _RULE_PUBLICATION_MAINTENANCE_PAGE,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_PREFIX as _RULE_PUBLICATION_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_STATE_PREFIX as _RULE_STATE_PREFIX,
)
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_REQUEST_TOPIC,
    RuleGenerationActivationCommandEvent,
)
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object


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


class MimirGovernanceRecoveryMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _catalog_draft_rule_ids: Any
        _catalog_governance_store: Any
        _checkpoint_rule_publication: Any
        _clock: Any
        _governance_state_store: Any
        _handle_rule_candidate: Any
        _handle_rule_generation_build_request: Any
        _handover_message: Any
        _investigation_candidates: Any
        _issue_fingerprints: Any
        _max_pending_candidates: Any
        _norns_issue_close_support: Any
        _operational_pending_targets: Any
        _pending_candidates: Any
        _persist_issue_fingerprint: Any
        _persist_promotion_record: Any
        _promotion_fail_count: Any
        _promotion_outcome_reader: Any
        _promotion_pass_count: Any
        _promotion_persist_pending: Any
        _promotion_persist_tasks: Any
        _promotion_publish_tasks: Any
        _promotions: Any
        _provider_timeout_seconds: Any
        _publish_claimed_rule_publication: Any
        _publish_rule_or_policy_promotion: Any
        _published_issue_close_evidence: Any
        _published_operational_targets: Any
        _published_promotion_keys: Any
        _quarantined_candidates: Any
        _rebuild_candidate_indexes: Any
        _record_norns_issue_close_support: Any
        _record_rule_generation_activation_result: Any
        _record_rule_generation_validation_result: Any
        _regression_runner: Any
        _retain_rule_generation_activation_command: Any
        _review_locks: Any
        _reviewed_repository_prefixes: Any
        _rule_deprecation_reader: Any
        _rule_generation_activation_binder: Any
        _rule_generation_build_handler: Any
        _rule_generation_state_store: Any
        _rule_source_poller: Any
        _shadow_dwell_thresholds: Any
        _test_context_message: Any

    async def recover_governance_state(self) -> int:
        """Restore durable rule, issue, investigation, and quarantine projections."""
        store = self._governance_state_store
        if store is None:
            return 0
        restored = 0
        restored += await self._recover_rule_rows(store)
        restored += await self._recover_rule_publications(store)
        restored += await self._recover_issue_rows(store)
        restored += await self._catalog_governance_store.recover(
            investigation_candidates=self._investigation_candidates,
            quarantined_candidates=self._quarantined_candidates,
            max_pending_candidates=self._max_pending_candidates,
            max_quarantine=self._quarantined_candidates.maxlen or _MAX_QUARANTINE,
        )
        return int(restored)

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._test_context_message(topic, payload, self.record_behavior):
            return
        if topic == "object.issue":
            await self._handle_issue(payload)
        elif topic == "object.rule-candidate":
            if self._record_norns_issue_close_support(payload):
                return
            if await self._handover_message(topic, payload):
                return
            lock_key = str(payload.get("idempotency_key") or payload.get("correlation_id") or "")
            if not lock_key:
                lock_key = repr(sorted(payload))
            lock = self._review_locks.setdefault(lock_key, asyncio.Lock())
            try:
                async with lock:
                    await self._handle_rule_candidate(payload)
                    await self._refresh_issue_candidate_counts_for_candidate(payload)
            finally:
                if not lock.locked() and self._review_locks.get(lock_key) is lock:
                    self._review_locks.pop(lock_key, None)
        elif topic == RULE_GENERATION_BUILD_REQUEST_TOPIC:
            await self._handle_rule_generation_build_request(payload)
        elif (
            topic == "object.retrieval-validation"
            and payload.get("event_type") == "rule.semantic_generation.validation.completed.v1"
        ):
            await self._record_rule_generation_validation_result(payload)
        elif topic == RULE_GENERATION_ACTIVATION_COMMAND_TOPIC:
            command = RuleGenerationActivationCommandEvent.model_validate(payload)
            binder = self._rule_generation_activation_binder
            if binder is None:
                raise RuntimeError("Mimir Rule generation activation binder is unavailable")
            await self._retain_rule_generation_activation_command(command)
            await binder.handle(command)
        elif topic == RULE_GENERATION_ACTIVATION_RESULT_TOPIC:
            await self._record_rule_generation_activation_result(payload)
        else:
            self.record_behavior("typed_message:ignored")

    async def _recover_rule_rows(self, store: StateStore) -> int:
        restored = 0
        offset = 0
        while restored < _MAX_ISSUE_FINGERPRINTS:
            rows, _total = await store.read_state_page(
                f"{_RULE_STATE_PREFIX}/",
                limit=min(_GOVERNANCE_RECOVERY_PAGE, _MAX_ISSUE_FINGERPRINTS - restored),
                offset=offset,
            )
            if not rows:
                return restored
            for row in rows:
                rule_id = str(row.get("rule_id") or "")
                state = str(row.get("state") or "")
                source = str(row.get("source") or "")
                if not rule_id or state not in {"shadow", "enforce", "retired"} or not source:
                    raise ValueError("Mimir durable rule state is invalid")
                self._promotions[rule_id] = RulePromotion(
                    rule_id=rule_id,
                    state=state,
                    source=source,
                    updated_at=(
                        row.get("updated_at") if isinstance(row.get("updated_at"), str) else None
                    ),
                )
                restored += 1
            offset += len(rows)
        self.record_behavior("governance_recovery:rules_deferred")
        return restored

    async def _recover_issue_rows(self, store: StateStore) -> int:
        restored = 0
        offset = 0
        while restored < _MAX_ISSUE_FINGERPRINTS:
            rows, _total = await store.read_state_page(
                f"{_ISSUE_FINGERPRINT_PREFIX}/",
                limit=min(_GOVERNANCE_RECOVERY_PAGE, _MAX_ISSUE_FINGERPRINTS - restored),
                offset=offset,
            )
            if not rows:
                return restored
            for row in rows:
                fingerprint = str(row.get("fingerprint") or "")
                if not fingerprint:
                    raise ValueError("Mimir durable issue fingerprint is invalid")
                self._issue_fingerprints.set(
                    fingerprint,
                    {
                        "fingerprint": fingerprint,
                        "issue_number": row.get("issue_number"),
                        "created": row.get("created") is True,
                        "correlation_id": str(row.get("correlation_id") or ""),
                        "open": row.get("open") is not False,
                        "candidate_count": row.get("candidate_count"),
                    },
                )
                restored += 1
            offset += len(rows)
        self.record_behavior("governance_recovery:issues_deferred")
        return restored

    async def _recover_rule_publications(
        self,
        store: StateStore,
        *,
        limit: int = _MAX_PROMOTION_PERSIST_QUEUE,
    ) -> int:
        if self.bus is None:
            return 0
        published = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = min(
                _GOVERNANCE_RECOVERY_PAGE,
                limit - attempted,
            )
            pending_rows, _pending_total = await store.read_state_page(
                f"{_RULE_PUBLICATION_PREFIX}/",
                limit=remaining,
                field="status",
                value="pending",
            )
            publishing_rows, _publishing_total = await store.read_state_page(
                f"{_RULE_PUBLICATION_PREFIX}/",
                limit=remaining,
                field="status",
                value="publishing",
            )
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                payload = row.get("payload")
                topic = str(row.get("topic") or "")
                idempotency_key = str(row.get("idempotency_key") or "")
                if not isinstance(payload, dict) or topic not in {"object.rule", "object.policy"}:
                    self.record_behavior("promotion:publication_recovery_invalid_row")
                    attempted += 1
                    continue
                if idempotency_key in attempted_keys:
                    continue
                attempted_keys.add(idempotency_key)
                attempted += 1
                try:
                    if await self._publish_claimed_rule_publication(
                        topic=topic,
                        payload=dict(payload),
                        idempotency_key=idempotency_key,
                    ):
                        self._published_promotion_keys.add(idempotency_key)
                        if payload.get("kind") == "catalog_review_outcome":
                            self._published_issue_close_evidence.add(idempotency_key)
                        published += 1
                        progress += 1
                except Exception:
                    self.record_behavior("promotion:publication_recovery_failed")
                    continue
            if progress == 0:
                break
        if published:
            self.record_behavior("promotion:publication_recovered", published)
        if attempted >= limit:
            self.record_behavior("promotion:publication_recovery_deferred")
        return published

    async def _handle_issue(self, payload: dict[str, Any]) -> None:
        """Retain Saga-owned issue fingerprints for candidate closure linkage."""
        if payload.get("producer_principal") != "Saga":
            self.record_behavior("issue_fingerprint:rejected")
            raise ValueError("Mimir issue fingerprints MUST be published by Saga")
        fingerprint = str(payload.get("fingerprint") or "").strip()
        issue_number = payload.get("issue_number")
        correlation_id = str(payload.get("correlation_id") or "").strip()
        if (
            not fingerprint
            or not correlation_id
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
        ):
            self.record_behavior("issue_fingerprint:rejected")
            raise ValueError("Mimir issue fingerprint payload is malformed")
        record = {
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "created": payload.get("created") is True,
            "correlation_id": correlation_id,
            "open": payload.get("open", True) is not False,
            "candidate_count": self._candidate_count_for_fingerprint(fingerprint),
        }
        self._issue_fingerprints.set(fingerprint, record)
        await self._persist_issue_fingerprint(record)
        self.record_behavior("issue_fingerprint:accepted")

    def _candidate_count_for_fingerprint(self, fingerprint: str) -> int:
        count = 0
        for candidate in self._pending_candidates:
            evidence = candidate.get("evidence")
            if isinstance(evidence, dict) and evidence.get("fingerprint") == fingerprint:
                count += 1
        return count

    async def _refresh_issue_candidate_counts_for_candidate(
        self,
        candidate: dict[str, Any],
    ) -> None:
        evidence = candidate.get("evidence")
        fingerprint = str(evidence.get("fingerprint") or "") if isinstance(evidence, dict) else ""
        if not fingerprint or self._issue_fingerprints.get(fingerprint) is None:
            return
        await self._refresh_issue_candidate_count(fingerprint)

    async def _refresh_issue_candidate_counts_for_rule(self, _rule_id: str) -> None:
        for fingerprint, record in tuple(self._issue_fingerprints.items()):
            count = self._candidate_count_for_fingerprint(fingerprint)
            if record.get("candidate_count") != count:
                updated = {**record, "candidate_count": count}
                self._issue_fingerprints.set(fingerprint, updated)
                await self._persist_issue_fingerprint(updated)

    async def _refresh_issue_candidate_count(self, fingerprint: str) -> None:
        record = self._issue_fingerprints.get(fingerprint)
        if record is None:
            return
        count = self._candidate_count_for_fingerprint(fingerprint)
        if record.get("candidate_count") == count:
            return
        updated = {**record, "candidate_count": count}
        self._issue_fingerprints.set(fingerprint, updated)
        await self._persist_issue_fingerprint(updated)
        self.record_behavior("issue_fingerprint:candidate_count_updated")


__all__ = ["MimirGovernanceRecoveryMixin"]
