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

from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
)
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    new_publication_claim_owner,
    publish_claimed_outbox,
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


class MimirRulePublicationMixin:
    """Behavior-preserving extracted runtime methods."""

    async def _publish_rule_or_policy_promotion(
        self: Any,
        promotion: RulePromotion,
        *,
        reviewed_change_ref: str | None = None,
        reviewed_package_digest: str | None = None,
    ) -> None:
        topic = _promotion_topic(promotion.rule_id, promotion.source)
        idempotency_key = stable_idempotency_key(
            "mimir-promotion",
            topic,
            promotion.rule_id,
            promotion.state,
            promotion.source,
            reviewed_change_ref or "",
        )
        if idempotency_key in self._published_promotion_keys:
            self.record_behavior("promotion:publication_duplicate")
            return
        correlation_id = stable_idempotency_key(
            "mimir-promotion-correlation",
            topic,
            promotion.rule_id,
            promotion.state,
            reviewed_change_ref or "",
        )
        payload = {
            "kind": "rule_promotion" if topic == "object.rule" else "policy_promotion",
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "rule_id": promotion.rule_id,
            "state": promotion.state,
            "source": promotion.source,
            "updated_at": promotion.updated_at,
            "reviewed_change_ref": reviewed_change_ref,
            "reviewed_package_digest": reviewed_package_digest,
            "grants_execution_authority": False,
        }
        if topic == "object.policy":
            payload["policy_id"] = promotion.rule_id
        if self.bus is None:
            self.record_behavior("promotion:publication_transport_unavailable")
            return
        if not await self._checkpoint_rule_publication(
            topic=topic,
            payload=payload,
            idempotency_key=idempotency_key,
        ):
            self._published_promotion_keys.add(idempotency_key)
            self.record_behavior("promotion:publication_duplicate")
            return
        try:
            published = await self._publish_claimed_rule_publication(
                topic=topic,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except Exception:
            self.record_behavior("promotion:publication_failed")
            raise
        if not published:
            self.record_behavior("promotion:publication_duplicate")
            return
        self._published_promotion_keys.add(idempotency_key)
        self.record_behavior("promotion:published")

    def _promotion_publish_done(self: Any, task: asyncio.Task[Any]) -> None:
        self._promotion_publish_tasks.discard(task)
        try:
            task.result()
        except Exception:
            self.record_behavior("promotion:publication_failed")
            return
        self.record_behavior("promotion:published")

    async def _checkpoint_rule_publication(
        self: Any,
        *,
        topic: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> bool:
        store = self._governance_state_store
        if store is None:
            return True
        key = _rule_publication_key(idempotency_key)
        record = {
            "kind": "mimir_rule_publication",
            "revision": 1,
            "status": "pending",
            "topic": topic,
            "idempotency_key": idempotency_key,
            "correlation_id": str(payload.get("correlation_id") or ""),
            "payload": dict(payload),
        }
        created = await store.write_state_if_absent(key, record)
        if created:
            return True
        stored = await store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Mimir rule publication row disappeared")
        if stored.get("status") == "published":
            if stored.get("payload") not in (None, record["payload"]):
                raise RuntimeError("Mimir rule publication idempotency collision")
            return False
        if stored.get("payload") != record["payload"]:
            raise RuntimeError("Mimir rule publication idempotency collision")
        return True

    async def _publish_claimed_rule_publication(
        self: Any,
        *,
        topic: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> bool:
        if self.bus is None:
            return False
        bus = self.bus
        claim = await self._claim_rule_publication(idempotency_key)
        return await publish_claimed_outbox(
            claim,
            publish=lambda: bus.publish("Mimir", topic, payload),
            mark_published=lambda active_claim: self._mark_rule_publication_published(
                idempotency_key,
                active_claim,
            ),
            release=lambda active_claim: self._release_rule_publication_claim(
                idempotency_key,
                active_claim,
            ),
            lease=_RULE_PUBLICATION_CLAIM_LEASE,
        )

    async def _claim_rule_publication(
        self: Any,
        idempotency_key: str,
    ) -> PublicationClaim | None:
        store = self._governance_state_store
        if store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._clock().isoformat(),
            )
        key = _rule_publication_key(idempotency_key)
        for attempt in range(_MAX_PROMOTION_PERSIST_ATTEMPTS):
            stored = await store.read_state(key)
            if stored is None:
                raise RuntimeError("Mimir rule publication row disappeared")
            if stored.get("status") == "published":
                return None
            now = self._clock()
            if stored.get("status") == "publishing" and not claim_expired(
                claimed_at=stored.get("claimed_at"),
                now=now,
                lease=_RULE_PUBLICATION_CLAIM_LEASE,
            ):
                return None
            if stored.get("status") not in {"pending", "publishing"}:
                raise RuntimeError("Mimir rule publication state is invalid")
            revision = int(stored.get("revision", 1))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            advanced = await store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "status": "publishing",
                    "claim_owner": claim_owner,
                    "claimed_at": claimed_at,
                },
                expected_revision=revision,
            )
            if advanced:
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Mimir rule publication claim CAS did not converge")

    async def _mark_rule_publication_published(
        self: Any,
        idempotency_key: str,
        claim: PublicationClaim,
    ) -> bool:
        store = self._governance_state_store
        if store is None:
            return True
        key = _rule_publication_key(idempotency_key)
        for _attempt in range(_MAX_PROMOTION_PERSIST_ATTEMPTS):
            stored = await store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return False
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await store.compare_and_set_state(
                key,
                {
                    "kind": "mimir_rule_publication",
                    "revision": revision + 1,
                    "status": "published",
                    "topic": str(stored.get("topic") or ""),
                    "idempotency_key": idempotency_key,
                    "correlation_id": str(stored.get("correlation_id") or ""),
                    "payload": dict(stored.get("payload") or {}),
                },
                expected_revision=revision,
            )
            if advanced:
                await store.delete_states_beyond(
                    f"{_RULE_PUBLICATION_PREFIX}/",
                    retain_newest=_MAX_PROMOTION_PERSIST_QUEUE,
                )
                return True
        raise RuntimeError("Mimir rule publication CAS did not converge")

    async def _release_rule_publication_claim(
        self: Any,
        idempotency_key: str,
        claim: PublicationClaim,
    ) -> None:
        store = self._governance_state_store
        if store is None:
            return
        key = _rule_publication_key(idempotency_key)
        for attempt in range(_MAX_PROMOTION_PERSIST_ATTEMPTS):
            stored = await store.read_state(key)
            if stored is None or stored.get("status") != "publishing":
                return
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return
            revision = int(stored.get("revision", 1))
            advanced = await store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "status": "pending",
                    "claim_owner": "",
                    "claimed_at": "",
                },
                expected_revision=revision,
            )
            if advanced:
                return
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Mimir rule publication release CAS did not converge")


__all__ = ["MimirRulePublicationMixin"]
