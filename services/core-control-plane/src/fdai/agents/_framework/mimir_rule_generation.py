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
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_REQUEST_TOPIC,
    RULE_GENERATION_BUILD_RESULT_TOPIC,
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
    RuleGenerationBuildRequestEvent,
    RuleGenerationValidationResultEvent,
)

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


class MimirRuleGenerationMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _catalog_draft_rule_ids: Any
        _catalog_governance_store: Any
        _checkpoint_rule_publication: Any
        _clock: Any
        _governance_state_store: Any
        _handle_rule_candidate: Any
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
        _recover_rule_publications: Any
        _refresh_issue_candidate_counts_for_rule: Any
        _regression_runner: Any
        _review_locks: Any
        _reviewed_repository_prefixes: Any
        _rule_deprecation_reader: Any
        _rule_generation_activation_binder: Any
        _rule_generation_build_handler: Any
        _rule_generation_state_store: Any
        _rule_source_poller: Any
        _shadow_dwell_thresholds: Any
        _test_context_message: Any

    async def request_rule_generation(self, request: RuleGenerationBuildRequestEvent) -> None:
        """Publish one exact no-authority generation build request as Mimir."""

        validated = RuleGenerationBuildRequestEvent.model_validate(request.model_dump())
        if self.bus is None:
            raise RuntimeError("Mimir Rule generation build transport is unavailable")
        await self.bus.publish(
            "Mimir",
            RULE_GENERATION_BUILD_REQUEST_TOPIC,
            validated.model_dump(mode="json"),
        )

    async def _handle_rule_generation_build_request(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            self.record_behavior("rule_generation_build_request:rejected_owner")
            raise ValueError("Rule generation build request MUST be published by Mimir")
        request = RuleGenerationBuildRequestEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationBuildRequestEvent.model_fields
                if field in payload
            }
        )
        handler = self._rule_generation_build_handler
        if handler is None:
            raise RuntimeError("Mimir Rule generation build handler is unavailable")
        result = await handler.handle(request)
        if self.bus is None:
            raise RuntimeError("Mimir Rule generation build transport is unavailable")
        result_payload = result.model_dump(mode="json")
        result_payload["correlation_id"] = request.correlation_id
        await self.bus.publish(
            "Mimir",
            RULE_GENERATION_BUILD_RESULT_TOPIC,
            result_payload,
        )
        self.record_behavior("rule_generation_build_result_published")

    async def _record_rule_generation_validation_result(
        self,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("producer_principal") != "Heimdall":
            self.record_behavior("rule_generation_validation:rejected_owner")
            raise ValueError("Rule generation validation MUST be published by Heimdall")
        result = RuleGenerationValidationResultEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationValidationResultEvent.model_fields
                if field in payload
            }
        )
        store = self._rule_generation_state_store
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        receipt_key = f"{_RULE_GENERATION_VALIDATION_PREFIX}{result.idempotency_key}"
        receipt = {
            "kind": "rule_semantic_generation_validation_result",
            "idempotency_key": result.idempotency_key,
            "result_digest": result.result_digest,
            "generation_id": result.build_result.generation.generation_id,
            "valid": result.valid,
            "validation_receipt_digest": result.validation_receipt_digest,
            "validated_at": result.validated_at.isoformat(),
            "projection_only": True,
            "grants_execution_authority": False,
        }
        created = await store.write_state_with_audit_if_absent(
            receipt_key,
            receipt,
            {
                **receipt,
                "principal": "Mimir",
                "topic": "object.retrieval-validation",
            },
        )
        if created:
            self.record_behavior("rule_generation_validation_result_recorded")
        else:
            existing = await store.read_state(receipt_key)
            if existing is None or existing.get("result_digest") != result.result_digest:
                raise ValueError("Rule generation validation result idempotency conflict")
            self.record_behavior("rule_generation_validation_result_duplicate")
        if result.valid:
            await self._publish_rule_generation_activation_command(result)
        await store.delete_states_beyond(
            _RULE_GENERATION_VALIDATION_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _publish_rule_generation_activation_command(
        self,
        result: RuleGenerationValidationResultEvent,
    ) -> None:
        store = self._rule_generation_state_store
        binder = self._rule_generation_activation_binder
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        if binder is None:
            raise RuntimeError("Mimir Rule generation activation binder is unavailable")
        command_key = f"{_RULE_GENERATION_COMMAND_PREFIX}{result.idempotency_key}"
        existing = await store.read_state(command_key)
        if existing is None:
            await binder.bind_validation_result(result)
            target = result.build_result.generation
            prior = await binder.active_generation_identity(target.corpus.value)
            commanded_at = max(self._clock(), result.validated_at)
            candidate = RuleGenerationActivationCommandEvent.create(
                validation_result=result,
                expected_active_generation=prior,
                commanded_at=commanded_at,
            )
            payload = candidate.model_dump(mode="json")
            created = await store.write_state_with_audit_if_absent(
                command_key,
                payload,
                {
                    "kind": "rule_semantic_generation_activation_command",
                    "principal": "Mimir",
                    "idempotency_key": candidate.idempotency_key,
                    "command_digest": candidate.command_digest,
                    "generation_id": target.generation_id,
                    "grants_execution_authority": False,
                },
            )
            if created:
                command = candidate
                self.record_behavior("rule_generation_activation_command_recorded")
            else:
                raced = await store.read_state(command_key)
                if raced is None:
                    raise RuntimeError("Mimir Rule generation activation command is unavailable")
                command = RuleGenerationActivationCommandEvent.model_validate(raced)
        else:
            command = RuleGenerationActivationCommandEvent.model_validate(existing)
        if command.validation_result.result_digest != result.result_digest:
            raise ValueError("Rule generation activation command idempotency conflict")
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                await binder.publish_command(command)
        except TimeoutError:
            self.record_behavior("rule_generation_activation_command_timeout")
            raise
        self.record_behavior("rule_generation_activation_command_published")
        await store.delete_states_beyond(
            _RULE_GENERATION_COMMAND_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _retain_rule_generation_activation_command(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> None:
        store = self._rule_generation_state_store
        if store is None:
            return
        command_key = (
            f"{_RULE_GENERATION_COMMAND_PREFIX}{command.validation_result.idempotency_key}"
        )
        existing = await store.read_state(command_key)
        if existing is not None:
            retained = RuleGenerationActivationCommandEvent.model_validate(existing)
            if retained.command_digest != command.command_digest:
                raise ValueError("Rule generation activation command idempotency conflict")
            return
        await store.write_state_with_audit_if_absent(
            command_key,
            command.model_dump(mode="json"),
            {
                "kind": "rule_semantic_generation_activation_command",
                "principal": "Mimir",
                "idempotency_key": command.idempotency_key,
                "command_digest": command.command_digest,
                "generation_id": (command.validation_result.build_result.generation.generation_id),
                "grants_execution_authority": False,
            },
        )
        await store.delete_states_beyond(
            _RULE_GENERATION_COMMAND_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _record_rule_generation_activation_result(self, payload: dict[str, Any]) -> None:
        producer = payload.get("producer_principal")
        if producer is not None and producer != "Mimir":
            self.record_behavior("rule_generation_activation_result_rejected_owner")
            raise ValueError("Rule generation activation result MUST be published by Mimir")
        result_payload = dict(payload)
        result_payload.pop("producer_principal", None)
        result = RuleGenerationActivationResultEvent.model_validate(result_payload)
        store = self._rule_generation_state_store
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        command_key = (
            f"{_RULE_GENERATION_COMMAND_PREFIX}{result.command.validation_result.idempotency_key}"
        )
        command_record = await store.read_state(command_key)
        if command_record is None:
            self.record_behavior("rule_generation_activation_result_rejected_unbound")
            raise ValueError("Rule generation activation result has no issued command")
        command = RuleGenerationActivationCommandEvent.model_validate(command_record)
        if command.command_digest != result.command.command_digest:
            self.record_behavior("rule_generation_activation_result_rejected_unbound")
            raise ValueError("Rule generation activation result command identity mismatch")
        receipt_key = f"{_RULE_GENERATION_RECEIPT_PREFIX}{result.idempotency_key}"
        receipt = {
            "kind": "rule_semantic_generation_activation_result",
            "idempotency_key": result.idempotency_key,
            "result_digest": result.result_digest,
            "status": result.status.value,
            "generation_id": (
                result.command.validation_result.build_result.generation.generation_id
            ),
            "completed_at": result.completed_at.isoformat(),
            "projection_only": True,
            "grants_execution_authority": False,
        }
        created = await store.write_state_with_audit_if_absent(
            receipt_key,
            receipt,
            {
                **receipt,
                "principal": "Mimir",
                "topic": RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
            },
        )
        if created:
            self.record_behavior("rule_generation_activation_result_recorded")
            await store.delete_states_beyond(
                _RULE_GENERATION_RECEIPT_PREFIX,
                retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
            )
            return
        existing = await store.read_state(receipt_key)
        if existing is None or existing.get("result_digest") != result.result_digest:
            raise ValueError("Rule generation activation result idempotency conflict")
        self.record_behavior("rule_generation_activation_result_duplicate")


__all__ = ["MimirRuleGenerationMixin"]
