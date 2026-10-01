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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirDeprecationCandidate,
    norns_issue_close_support,
    promotion_outcome_is_authoritative,
    regression_result_is_clean,
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


class MimirGovernanceMaintenanceMixin:
    """Behavior-preserving extracted runtime methods."""

    async def maintenance_tick(self: Any) -> None:
        await Agent.maintenance_tick(self)
        await self._poll_rule_sources()
        await self._publish_issue_close_promotion_evidence()
        if self._governance_state_store is not None and self.bus is not None:
            await self._recover_rule_publications(
                self._governance_state_store,
                limit=_RULE_PUBLICATION_MAINTENANCE_PAGE,
            )
        await self._record_deprecation_cycle()

    async def _poll_rule_sources(self: Any) -> None:
        poller = self._rule_source_poller
        if poller is None:
            self._last_rule_source_poll = {
                "status": "unbound",
                "outcome": "bounded_noop",
                "checked": 0,
            }
            self.record_behavior("maintenance:rule_source_poll_unbound")
            return
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                result = await poller.poll_rule_sources(
                    limit=_MAX_MAINTENANCE_RECORDS,
                    now=self._clock(),
                )
        except TimeoutError:
            self._last_rule_source_poll = {
                "status": "timeout",
                "outcome": "bounded_noop",
                "checked": 0,
            }
            self.record_behavior("maintenance:rule_source_poll_timeout")
            return
        except Exception:
            self._last_rule_source_poll = {
                "status": "failed",
                "outcome": "bounded_noop",
                "checked": 0,
            }
            self.record_behavior("maintenance:rule_source_poll_failed")
            return
        self._last_rule_source_poll = {
            "status": "measured",
            "outcome": "audit_evidence",
            "checked": result.checked,
            "changed": result.changed,
            "evidence_ref": result.evidence_ref,
        }
        self.record_behavior("maintenance:rule_source_polled")

    async def _publish_issue_close_promotion_evidence(self: Any) -> None:
        reader = self._promotion_outcome_reader
        runner = self._regression_runner
        if reader is None or runner is None:
            self._last_regression_suite = {
                "status": "unbound",
                "outcome": "bounded_noop",
                "promotion_reader_bound": reader is not None,
                "regression_runner_bound": runner is not None,
            }
            self.record_behavior("maintenance:promotion_evidence_unbound")
            return
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                outcomes = await reader.read_promotion_outcomes(
                    limit=_MAX_MAINTENANCE_RECORDS,
                    now=self._clock(),
                )
        except TimeoutError:
            self._last_regression_suite = {
                "status": "timeout",
                "outcome": "bounded_noop",
                "promotion_outcomes": 0,
                "regressions_attempted": 0,
                "evidence_published": 0,
            }
            self.record_behavior("maintenance:promotion_outcome_reader_timeout")
            return
        except Exception:
            self._last_regression_suite = {
                "status": "failed",
                "outcome": "bounded_noop",
                "promotion_outcomes": 0,
                "regressions_attempted": 0,
                "evidence_published": 0,
            }
            self.record_behavior("maintenance:promotion_outcome_reader_failed")
            return
        attempted = 0
        published = 0
        for outcome in outcomes[:_MAX_MAINTENANCE_RECORDS]:
            if not promotion_outcome_is_authoritative(outcome):
                self.record_behavior("promotion_evidence:invalid_outcome")
                continue
            idempotency_key = _issue_close_evidence_idempotency_key(outcome)
            if await self._rule_publication_exists(idempotency_key):
                self._published_issue_close_evidence.add(idempotency_key)
                self.record_behavior("promotion_evidence:duplicate")
                continue
            attempted += 1
            try:
                async with asyncio.timeout(self._provider_timeout_seconds):
                    result = await runner.run_regression(outcome, now=self._clock())
            except TimeoutError:
                self.record_behavior("promotion_evidence:regression_timeout")
                continue
            except Exception:
                self.record_behavior("promotion_evidence:regression_failed")
                continue
            if not regression_result_is_clean(result):
                self.record_behavior("promotion_evidence:regression_not_clean")
                continue
            if await self._publish_issue_close_evidence(outcome, result.started_at.isoformat()):
                published += 1
        self._last_regression_suite = {
            "status": "measured",
            "outcome": "audit_evidence",
            "promotion_outcomes": len(outcomes),
            "regressions_attempted": attempted,
            "evidence_published": published,
        }

    async def _publish_issue_close_evidence(
        self: Any,
        outcome: MimirCatalogPromotionOutcome,
        clean_regression_started_at: str,
    ) -> bool:
        idempotency_key = _issue_close_evidence_idempotency_key(outcome)
        if idempotency_key in self._published_issue_close_evidence:
            self.record_behavior("promotion_evidence:duplicate")
            return False
        payload = {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": outcome.correlation_id,
            "idempotency_key": idempotency_key,
            "outcome": outcome.outcome,
            "problem_fingerprint": outcome.problem_fingerprint,
            "fingerprint": outcome.problem_fingerprint,
            "promotion_pr": outcome.promotion_pr,
            "clean_regression_started_at": clean_regression_started_at,
            "rule_id": outcome.rule_id,
            "candidate_digest": outcome.candidate_digest,
            "package_digest": outcome.package_digest,
            "review_ref": outcome.review_ref,
            "norns_issue_close_support": self._norns_issue_close_support.get(
                outcome.problem_fingerprint
            ),
            "grants_issue_close_authority": False,
        }
        if self.bus is None:
            self.record_behavior("promotion_evidence:transport_unavailable")
            return False
        if not await self._checkpoint_rule_publication(
            topic="object.rule",
            payload=payload,
            idempotency_key=idempotency_key,
        ):
            self._published_issue_close_evidence.add(idempotency_key)
            self.record_behavior("promotion_evidence:duplicate")
            return False
        if not await self._publish_claimed_rule_publication(
            topic="object.rule",
            payload=payload,
            idempotency_key=idempotency_key,
        ):
            self.record_behavior("promotion_evidence:duplicate")
            return False
        self._published_issue_close_evidence.add(idempotency_key)
        self.record_behavior("promotion_evidence:published")
        return True

    async def _record_deprecation_cycle(self: Any) -> None:
        reader = self._rule_deprecation_reader
        if reader is None:
            self._last_deprecation_cycle = {
                "status": "unbound",
                "outcome": "bounded_noop",
                "candidates": 0,
            }
            self.record_behavior("maintenance:deprecation_cycle_unbound")
            return
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                candidates = await reader.stale_or_retired_rules(
                    limit=_MAX_MAINTENANCE_RECORDS,
                    now=self._clock(),
                )
        except TimeoutError:
            self._last_deprecation_cycle = {
                "status": "timeout",
                "outcome": "bounded_noop",
                "candidates": 0,
            }
            self.record_behavior("maintenance:deprecation_cycle_timeout")
            return
        except Exception:
            self._last_deprecation_cycle = {
                "status": "failed",
                "outcome": "bounded_noop",
                "candidates": 0,
            }
            self.record_behavior("maintenance:deprecation_cycle_failed")
            return
        retained = 0
        for candidate in candidates[:_MAX_MAINTENANCE_RECORDS]:
            try:
                await self._persist_deprecation_candidate(candidate)
            except Exception:
                self.record_behavior("deprecation_cycle:candidate_failed")
                continue
            retained += 1
        self._last_deprecation_cycle = {
            "status": "measured",
            "outcome": "audit_evidence",
            "candidates": retained,
        }
        self.record_behavior("maintenance:deprecation_cycle_recorded")

    async def _persist_deprecation_candidate(
        self: Any, candidate: MimirDeprecationCandidate
    ) -> None:
        store = self._governance_state_store
        if store is None:
            self.record_behavior("deprecation_cycle:process_local")
            return
        candidate_key = stable_idempotency_key(
            "mimir-rule-deprecation",
            candidate.rule_id,
            candidate.reason,
        )
        key = f"{_DEPRECATION_CANDIDATE_PREFIX}/{candidate_key}"
        await store.write_state_with_audit_if_absent(
            key,
            {
                "kind": "mimir_rule_deprecation_candidate",
                "revision": 1,
                "rule_id": candidate.rule_id,
                "reason": candidate.reason,
                "evidence_ref": candidate.evidence_ref,
                "observed_at": candidate.observed_at.isoformat(),
                "catalog_mutated": False,
                "grants_authority": False,
            },
            {
                "kind": "mimir_rule_deprecation_candidate_recorded",
                "principal": "Mimir",
                "rule_id": candidate.rule_id,
                "reason": candidate.reason,
                "evidence_ref": candidate.evidence_ref,
                "grants_authority": False,
            },
        )
        await store.delete_states_beyond(
            f"{_DEPRECATION_CANDIDATE_PREFIX}/",
            retain_newest=_MAX_MAINTENANCE_RECORDS,
        )

    async def _rule_publication_exists(self: Any, idempotency_key: str) -> bool:
        if idempotency_key in self._published_issue_close_evidence:
            return True
        store = self._governance_state_store
        if store is None:
            return False
        stored = await store.read_state(_rule_publication_key(idempotency_key))
        if stored is None:
            return False
        if stored.get("status") == "published":
            self._published_issue_close_evidence.add(idempotency_key)
            return True
        return False

    def _record_norns_issue_close_support(self: Any, payload: Mapping[str, Any]) -> bool:
        support = norns_issue_close_support(payload)
        if support is None:
            return False
        self._norns_issue_close_support.set(str(support["fingerprint"]), support)
        self.record_behavior("norns_issue_close_support:recorded")
        return True


__all__ = ["MimirGovernanceMaintenanceMixin"]
