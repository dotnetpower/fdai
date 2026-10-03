"""Heimdall owns independent observation, bounded anomaly episodes and evidence relays.

Admin notifications retain per-initiator/action deduplication; observation grants no authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.heimdall_constants import (
    _DETECTION_READINESS_EVENT as _DETECTION_READINESS_EVENT,
)
from fdai.agents._framework.heimdall_constants import (
    _EPISODE_PREFIX as _EPISODE_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _FULL_SNAPSHOT_LIMIT as _FULL_SNAPSHOT_LIMIT,
)
from fdai.agents._framework.heimdall_constants import (
    _INCIDENT_CORRELATION_DISABLED as _INCIDENT_CORRELATION_DISABLED,
)
from fdai.agents._framework.heimdall_constants import (
    _MAX_KPI_SAMPLES as _MAX_KPI_SAMPLES,
)
from fdai.agents._framework.heimdall_constants import (
    _PENDING_READINESS_PREFIX as _PENDING_READINESS_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_CAS_ATTEMPTS as _PUBLICATION_CAS_ATTEMPTS,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_CLAIM_LEASE as _PUBLICATION_CLAIM_LEASE,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_MAINTENANCE_PAGE as _PUBLICATION_MAINTENANCE_PAGE,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_PREFIX as _PUBLICATION_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_RECOVERY_LIMIT as _PUBLICATION_RECOVERY_LIMIT,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES as _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES,
)
from fdai.agents._framework.heimdall_constants import (
    _READINESS_PREFIX as _READINESS_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _RULE_VALIDATION_TIMEOUT_SECONDS as _RULE_VALIDATION_TIMEOUT_SECONDS,
)
from fdai.agents._framework.heimdall_constants import (
    _SEVERITY_RANK as _SEVERITY_RANK,
)
from fdai.agents._framework.heimdall_constants import (
    _STATE_KEY as _STATE_KEY,
)
from fdai.agents._framework.heimdall_huginn_projection import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    evidence_conflict_record,
    recovery_effect_observation_record,
)
from fdai.agents._framework.heimdall_retrieval_validation import (
    retrieval_validation_from_event,
)
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    new_publication_claim_owner,
    publish_claimed_outbox,
)
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import CHAOS_ACTION_TYPES, SPECIALIST_EVENT_PREFIX
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_RESULT_TOPIC,
    RuleGenerationBuildResultEvent,
)

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object

AlerterHook = Callable[[dict[str, Any]], Awaitable[None]]
"""Var-provided hook that delivers the admin notification card."""

IncidentCandidateHook = Callable[[dict[str, Any]], Awaitable[bool]]
"""Composition hook returning whether the lifecycle accepted a candidate."""

ReadInvestigationHook = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]
"""Composition-provided read-only investigation responder."""

OperationalEvidenceHook = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]
"""Composition-provided bounded evidence collector for one operational Event."""


# Accepted publications must fit one broker request with envelope headroom.
_PUBLICATION_MAX_PAYLOAD_BYTES = 512 * 1024

_LOG = logging.getLogger("fdai.agents.heimdall")


def _kpi_measured(
    value: float,
    *,
    numerator: int | float,
    denominator: int | float,
    unit: str = "ratio",
) -> dict[str, Any]:
    return {
        "value": float(value),
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def _kpi_unavailable(evidence_state: str, reason: str, *, unit: str = "ratio") -> dict[str, Any]:
    return {
        "value": None,
        "evidence_state": evidence_state,
        "reason": reason,
        "numerator": 0,
        "denominator": 0,
        "unit": unit,
    }


def _ratio_kpi(numerator: object, denominator: object, *, reason: str) -> dict[str, Any]:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int | float)
        or not isinstance(denominator, int | float)
        or denominator <= 0
    ):
        return _kpi_unavailable("insufficient_sample", reason)
    return _kpi_measured(
        float(numerator) / float(denominator),
        numerator=numerator,
        denominator=denominator,
    )


def _mean_kpi(samples: deque[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples) / len(samples),
        numerator=len(samples),
        denominator=len(samples),
        unit=unit,
    )


class HeimdallPublicationRuntimeMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _action_semantics: Any
        _alert_counters: Any
        _alert_noise_message: Any
        _alert_windows: Any
        _alerter_hook: Any
        _clock: Any
        _detection_readiness: Any
        _detection_readiness_pass_order: Any
        _detection_readiness_pending: Any
        _dirty_episode_keys: Any
        _dirty_pending_readiness: Any
        _dirty_readiness_resources: Any
        _drop_episode: Any
        _emit_document_safety_signal: Any
        _episode_history: Any
        _forecast_clock: Any
        _forecast_context_message: Any
        _incident_candidate_hook: Any
        _incident_episode_ids: Any
        _incident_episode_severities: Any
        _maybe_classify_severity: Any
        _maybe_emit_anomaly: Any
        _maybe_send_admin_card: Any
        _observe_action_run: Any
        _observe_detection_readiness: Any
        _observe_t2_proposer_health: Any
        _operational_evidence_hook: Any
        _persist_state: Any
        _publication_lock: Any
        _publication_lock_refs: Any
        _publication_locks: Any
        _rate_threshold: Any
        _rate_window: Any
        _readiness_expected_dimensions: Any
        _readiness_observed_dimensions: Any
        _recent_episode_keys: Any
        _recent_events: Any
        _reserve_alert_slot: Any
        _rule_generation_validation_handler: Any
        _run_forecast_tick: Any
        _security_high_threshold: Any
        _security_recent: Any
        _stale_inventory_delays_seconds: Any
        _state_store: Any

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._alert_noise_message(topic, payload):
            return
        if topic == "object.action-run":
            await self._observe_action_run(payload)
        elif topic == RULE_GENERATION_BUILD_RESULT_TOPIC:
            await self._validate_rule_generation(payload)
        elif topic == "object.event" and not await self._forecast_context_message(payload):
            if payload.get("event_type") == "evidence.conflict.candidate.v1":
                await self._publish_evidence_conflict(payload)
                return
            if payload.get("event_type") == RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
                await self._publish_recovery_effect_observation(payload)
                return
            retrieval_validation = retrieval_validation_from_event(payload)
            if retrieval_validation is not None:
                await self._publish_retrieval_validation(retrieval_validation)
                return
            if str(payload.get("event_type") or "").startswith(SPECIALIST_EVENT_PREFIX):
                self.record_behavior("specialist_signal:deferred")
                return
            if payload.get("event_type") == _DETECTION_READINESS_EVENT:
                await self._observe_detection_readiness(payload)
                return
            if payload.get("event_type") == "forecast.evaluation_due":
                await self._run_forecast_tick(payload)
                return
            if str(payload.get("event_type") or "").startswith("control_plane.t2_proposer_"):
                await self._observe_t2_proposer_health(payload)
                return
            if (
                payload.get("kind") == "document_ingestion"
                and payload.get("event_type") == "document.inspected"
            ):
                await self._emit_document_safety_signal(payload)
                return
            await self._maybe_emit_anomaly(payload)
        elif topic == "object.chaos-experiment":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="chaos_experiment:invalid_producer",
            ):
                return
            await self._observe_chaos_experiment(payload)
        elif topic == "object.security-event":
            severity = await self._maybe_classify_severity(payload)
            if severity in ("high", "critical") and self._alerter_hook is not None:
                await self._maybe_send_admin_card(payload, severity)
        else:
            self.record_behavior("typed_message:ignored")

    async def _publish_evidence_conflict(self, payload: dict[str, Any]) -> None:
        """Validate one candidate and publish the authoritative immutable revision."""

        record = evidence_conflict_record(payload)
        if record is None:
            self.record_behavior("evidence_conflict:invalid_candidate")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall evidence-conflict bus is unavailable")
        await self._publish_once("object.evidence-conflict", record)
        self.record_behavior(f"evidence_conflict:{record['status']}")

    async def _publish_recovery_effect_observation(self, payload: dict[str, Any]) -> None:
        """Relay one external recovery post-effect observation onto the owned topic.

        Heimdall is the terminal effect observer, so the independent observation
        enters through Huginn and leaves on a Heimdall-owned topic that the
        privileged executor can never publish to. The relay proves provenance
        and shape only; it verifies no effect and grants no authority.
        """

        record = recovery_effect_observation_record(payload)
        if record is None:
            self.record_behavior("recovery_effect_observation:invalid_signal")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall recovery effect observation bus is unavailable")
        await self._publish_once("object.recovery-effect-observation", record)
        self.record_behavior("recovery_effect_observation:relayed")

    async def _publish_retrieval_validation(self, payload: dict[str, object]) -> None:
        self.record_behavior("semantic_retrieval_validation:accepted")
        if self.bus is None:
            raise RuntimeError("Heimdall retrieval validation bus is unavailable")
        await self._publish_once("object.retrieval-validation", payload)

    async def _validate_rule_generation(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            raise ValueError("Rule generation build result MUST be published by Mimir")
        build_result = RuleGenerationBuildResultEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationBuildResultEvent.model_fields
                if field in payload
            }
        )
        handler = self._rule_generation_validation_handler
        if handler is None:
            raise RuntimeError("Heimdall Rule generation validator is unavailable")
        try:
            async with asyncio.timeout(_RULE_VALIDATION_TIMEOUT_SECONDS):
                result = await handler.handle(build_result)
        except TimeoutError:
            self.record_behavior("rule_generation_validation:timeout")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall retrieval validation bus is unavailable")
        result_payload = result.model_dump(mode="json")
        result_payload["correlation_id"] = build_result.request.correlation_id
        result_payload.setdefault(
            "idempotency_key",
            stable_idempotency_key(
                "rule-generation-validation",
                build_result.request.correlation_id,
                result_payload,
            ),
        )
        await self._publish_once("object.retrieval-validation", result_payload)
        self.record_behavior("rule_generation_validation:published")

    async def _observe_chaos_experiment(self, proposal: dict[str, Any]) -> None:
        kind = str(proposal.get("kind") or "chaos_experiment_proposal")
        if kind != "chaos_experiment_proposal":
            self.record_behavior("chaos_experiment:ignored_non_proposal_kind")
            return
        experiment_id = str(proposal.get("experiment_id") or "")
        action_type = str(proposal.get("action_type") or "")
        raw_targets = proposal.get("targets")
        targets: tuple[str, ...] = ()
        if isinstance(raw_targets, list) and 1 <= len(raw_targets) <= 32:
            targets = tuple(
                item.strip()
                for item in raw_targets
                if isinstance(item, str)
                and item.strip()
                and len(item.strip()) <= 512
                and not any(
                    (ord(char) < 32 and char not in "\t") or ord(char) == 127
                    for char in item.strip()
                )
            )
        if (
            not experiment_id
            or action_type not in CHAOS_ACTION_TYPES
            or not targets
            or len(targets) != len(raw_targets or ())
            or len(set(targets)) != len(targets)
        ):
            self.record_behavior("chaos_experiment:invalid")
            return
        evidence_fields = (
            "causal_hypothesis_ref",
            "refutation_query_ref",
            "impact_envelope_id",
            "recovery_plan_id",
            "dry_run_receipt",
        )
        evidence_complete = all(str(proposal.get(field) or "").strip() for field in evidence_fields)
        anomaly = {
            "producer_principal": "Heimdall",
            "correlation_id": str(proposal.get("correlation_id") or experiment_id),
            "idempotency_key": stable_idempotency_key(
                "chaos-experiment-anomaly",
                str(proposal.get("correlation_id") or experiment_id),
                experiment_id,
                action_type,
                targets,
            ),
            "resource_id": targets[0],
            "target_type": "experiment",
            "event_type": "chaos_experiment_request",
            "action_type": action_type,
            "severity": "high",
            "incident_correlation": "correlate",
            "initiator_principal": "Loki",
            "human_approval_required": True,
            "evidence_complete": evidence_complete,
            "params": {
                "experiment_id": experiment_id,
                "targets": list(targets),
                **{field: str(proposal.get(field) or "") for field in evidence_fields},
            },
        }
        self.record_behavior(
            "chaos_experiment:grounded" if evidence_complete else "chaos_experiment:incomplete"
        )
        if self.bus is None:
            self.record_behavior("chaos_experiment:publication_unavailable")
            return
        await self._publish_once("object.anomaly", anomaly)

    async def _publish_once(self, topic: str, payload: dict[str, Any]) -> bool:
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            raise ValueError("Heimdall publication requires an idempotency_key")
        publication_digest = hashlib.sha256(f"{topic}:{idempotency_key}".encode()).hexdigest()
        state_key = f"{_PUBLICATION_PREFIX}{publication_digest}"
        if len(_canonical_payload_bytes(payload)) > _PUBLICATION_MAX_PAYLOAD_BYTES:
            self.record_behavior("publication:payload_too_large")
            raise ValueError("Heimdall publication payload exceeds the bounded outbox size")
        async with self._publication_lock(publication_digest):
            if self._state_store is not None:
                existing = await self._state_store.read_state(state_key)
                if existing is not None and existing.get("state") == "published":
                    self.record_behavior("publication:duplicate")
                    return False
                await self._state_store.write_state_if_absent(
                    state_key,
                    _publication_row(
                        topic=topic,
                        idempotency_key=idempotency_key,
                        payload=payload,
                        revision=1,
                        state="pending",
                    ),
                )
            if self.bus is None:
                return False
            bus = self.bus
            claim = await self._claim_publication(state_key, topic, idempotency_key, payload)
            return await publish_claimed_outbox(
                claim,
                publish=lambda: bus.publish("Heimdall", topic, payload),
                mark_published=lambda active_claim: self._mark_publication_published(
                    state_key,
                    topic,
                    idempotency_key,
                    payload,
                    active_claim,
                ),
                release=lambda active_claim: self._release_publication_claim(
                    state_key,
                    payload,
                    active_claim,
                ),
                lease=_PUBLICATION_CLAIM_LEASE,
            )

    async def recover_publications(self, *, limit: int = _PUBLICATION_RECOVERY_LIMIT) -> int:
        """Republish durable Heimdall publication intents left pending at restart."""

        if self._state_store is None or self.bus is None:
            return 0
        bus = self.bus
        recovered = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, _pending_total = await self._state_store.read_state_page(
                _PUBLICATION_PREFIX,
                limit=remaining,
                field="state",
                value="pending",
            )
            publishing_rows, _publishing_total = await self._state_store.read_state_page(
                _PUBLICATION_PREFIX,
                limit=remaining,
                field="state",
                value="publishing",
            )
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                topic = str(row.get("topic") or "")
                payload = row.get("payload")
                if topic not in {
                    "object.anomaly",
                    "object.drift",
                    "object.evidence-conflict",
                    "object.recovery-effect-observation",
                    "object.retrieval-validation",
                } or not isinstance(payload, dict):
                    self.record_behavior("publication:recovery_invalid_row")
                    attempted += 1
                    continue
                idempotency_key = str(row.get("idempotency_key") or "")
                publication_digest = hashlib.sha256(
                    f"{topic}:{idempotency_key}".encode()
                ).hexdigest()
                state_key = f"{_PUBLICATION_PREFIX}{publication_digest}"
                if state_key in attempted_keys:
                    continue
                attempted_keys.add(state_key)
                attempted += 1
                claim = await self._claim_publication(state_key, topic, idempotency_key, payload)
                recovered_payload = dict(payload)

                async def mark_recovered(
                    active_claim: PublicationClaim,
                    *,
                    state_key: str = state_key,
                    topic: str = topic,
                    idempotency_key: str = idempotency_key,
                    payload: dict[str, Any] = recovered_payload,
                ) -> bool:
                    return bool(
                        await self._mark_publication_published(
                            state_key,
                            topic,
                            idempotency_key,
                            payload,
                            active_claim,
                        )
                    )

                async def release_recovered(
                    active_claim: PublicationClaim,
                    *,
                    state_key: str = state_key,
                    payload: dict[str, Any] = recovered_payload,
                ) -> None:
                    await self._release_publication_claim(
                        state_key,
                        payload,
                        active_claim,
                    )

                async def publish_recovered(
                    *,
                    topic: str = topic,
                    payload: dict[str, Any] = recovered_payload,
                ) -> None:
                    await bus.publish("Heimdall", topic, payload)

                try:
                    if await publish_claimed_outbox(
                        claim,
                        publish=publish_recovered,
                        mark_published=mark_recovered,
                        release=release_recovered,
                        lease=_PUBLICATION_CLAIM_LEASE,
                    ):
                        recovered += 1
                        progress += 1
                except Exception:
                    self.record_behavior("publication:recovery_publish_failed")
                    continue
            if progress == 0:
                break
        return recovered

    async def maintenance_tick(self) -> None:
        await Agent.maintenance_tick(self)
        try:
            await self.recover_publications(limit=_PUBLICATION_MAINTENANCE_PAGE)
        except Exception:
            self.record_behavior("publication:maintenance_recovery_failed")

    async def _claim_publication(
        self,
        state_key: str,
        topic: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> PublicationClaim | None:
        if self._state_store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._forecast_clock().isoformat(),
            )
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None:
                raise RuntimeError("Heimdall publication row disappeared")
            if stored.get("state") == "published":
                return None
            if stored.get("topic") != topic or stored.get("idempotency_key") != idempotency_key:
                raise RuntimeError("Heimdall publication row is malformed")
            if stored.get("payload") != dict(payload):
                raise RuntimeError("Heimdall publication payload identity conflict")
            now = self._forecast_clock()
            if stored.get("state") == "publishing" and not claim_expired(
                claimed_at=stored.get("claimed_at"),
                now=now,
                lease=_PUBLICATION_CLAIM_LEASE,
            ):
                return None
            if stored.get("state") not in {"pending", "publishing"}:
                raise RuntimeError("Heimdall publication row is malformed")
            revision = int(stored.get("revision", 1))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "state": "publishing",
                    "claim_owner": claim_owner,
                    "claimed_at": claimed_at,
                },
                expected_revision=revision,
            )
            if advanced:
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication claim CAS retry limit exceeded")

    async def _mark_publication_published(
        self,
        state_key: str,
        topic: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> bool:
        if self._state_store is None:
            return True
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None or stored.get("state") == "published":
                return False
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                _publication_row(
                    topic=topic,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    revision=revision + 1,
                    state="published",
                ),
                expected_revision=revision,
            )
            if advanced:
                return True
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication mark CAS retry limit exceeded")

    async def _release_publication_claim(
        self,
        state_key: str,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> None:
        if self._state_store is None:
            return
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None or stored.get("state") != "publishing":
                return
            if stored.get("payload") != dict(payload):
                raise RuntimeError("Heimdall publication payload identity conflict")
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "state": "pending",
                    "claim_owner": "",
                    "claimed_at": "",
                },
                expected_revision=revision,
            )
            if advanced:
                return
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication release CAS retry limit exceeded")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _publication_row(
    *,
    topic: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    revision: int,
    state: str,
) -> dict[str, Any]:
    encoded = _canonical_payload_bytes(payload)
    row: dict[str, Any] = {
        "schema_version": "1.0.0",
        "revision": revision,
        "state": state,
        "topic": topic,
        "idempotency_key": idempotency_key,
        "payload_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }
    # Unpublished rows always keep the replay body; only published tombstones drop large bodies.
    if state != "published" or len(encoded) <= _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES:
        row["payload"] = dict(payload)
    return row


def _canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


__all__ = ["HeimdallPublicationRuntimeMixin"]
