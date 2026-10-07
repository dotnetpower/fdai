"""Typed event and durability runtime mixin for Forseti."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE

from fdai.agents._framework import forseti_durability
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.cross_vertical_candidates import is_cross_vertical_candidate
from fdai.agents._framework.forseti_constants import _MAX_RESOURCES
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.core.architecture_review import ArchitectureReviewObservation
from fdai.core.capacity import CapacityGraduationRecommendation, GraduationRecommendationStatus
from fdai.core.impact_analysis import (
    ChangeGraphEvidenceReceipt,
    change_graph_evidence_from_snapshot,
)
from fdai.shared.contracts.models import Mode

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus
    from fdai.agents._framework.forseti_decision_helpers import ChangeAssessor
    from fdai.core.architecture_review import OntologyArchitectureReviewLoop
    from fdai.core.operational_context import OperationalContextMaterializer
    from fdai.shared.providers.state_store import StateStore


def _rule_revision(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _rule_updated_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp


def _rule_state_is_newer(
    current: Mapping[str, str],
    *,
    incoming_revision: int | None,
    incoming_updated_at: datetime | None,
    incoming_source_digest: str,
) -> bool:
    current_revision = _rule_revision(current.get("revision"))
    if current_revision is not None or incoming_revision is not None:
        return incoming_revision is not None and (
            current_revision is None or incoming_revision > current_revision
        )
    current_updated_at = _rule_updated_at(current.get("updated_at"))
    if current_updated_at is not None or incoming_updated_at is not None:
        return incoming_updated_at is not None and (
            current_updated_at is None or incoming_updated_at > current_updated_at
        )
    current_digest = str(current.get("source_digest") or "")
    return bool(incoming_source_digest and incoming_source_digest != current_digest)


class ForsetiRuntimeEventsMixin:
    """Handle typed inputs and persisted rule/advice state."""

    bus: PantheonBus | None
    _architecture_review_loop: OntologyArchitectureReviewLoop | None
    _architecture_review_timeout_seconds: float
    _change_assessor: ChangeAssessor | None
    _change_assessment_timeout_seconds: float
    _operational_context: OperationalContextMaterializer | None
    _rule_state: BoundedLruDict[str, dict[str, str]]
    _forseti_state_store: StateStore | None
    _detection_readiness: BoundedLruDict[str, dict[str, str]]
    _rule_staleness_started_at: datetime
    _last_owner_rule_update_at: datetime | None
    _rule_staleness_window: timedelta

    if TYPE_CHECKING:

        async def _handover_message(self, topic: str, payload: dict[str, Any]) -> bool: ...

        async def _assignment_message(self, topic: str, payload: dict[str, Any]) -> bool: ...

        async def _alert_noise_message(self, topic: str, payload: dict[str, Any]) -> bool: ...

        async def _ingest_cross_vertical_candidate(
            self,
            topic: str,
            payload: dict[str, Any],
        ) -> None: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def _record_detection_readiness(self, payload: dict[str, Any]) -> None: ...

        async def _run_retrospective_what_if(self, request: Mapping[str, Any]) -> None: ...

        async def judge_document_ingestion(self, event: dict[str, Any]) -> dict[str, Any]: ...

        async def judge_document_safety(self, signal: dict[str, Any]) -> dict[str, Any]: ...

        async def _judge_forecast(self, forecast: dict[str, Any]) -> dict[str, Any] | None: ...

        async def maybe_request_arbitration(
            self,
            event: dict[str, Any],
        ) -> dict[str, Any] | None: ...

        async def judge(
            self,
            event: dict[str, Any],
            *,
            source_mode: Mode | None = None,
        ) -> dict[str, Any] | None: ...

        async def _ingest_domain_signal(
            self,
            topic: str,
            payload: dict[str, Any],
        ) -> dict[str, Any] | None: ...

        async def _judge_capacity_forecast(
            self,
            forecast: dict[str, Any],
        ) -> dict[str, Any] | None: ...

        async def _record_arbitration(self, decision: dict[str, Any]) -> None: ...

        def _now(self) -> datetime: ...

        def _run_verdict_coherence_self_test(self) -> None: ...

        def _refresh_novelty_drift_signal(self) -> None: ...

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._handover_message(topic, payload):
            return
        if await self._assignment_message(topic, payload):
            return
        if await self._alert_noise_message(topic, payload):
            return
        if (
            topic == "object.event"
            and payload.get("event_type") == INCIDENT_INTERVENTION_EVENT_TYPE
            and payload.get("producer_principal") not in {None, "Huginn"}
        ):
            raise ValueError("incident guidance requires the Huginn-owned normalized Event")
        owner_rejection_behaviors = {
            "object.change": "typed_input:rejected_owner",
            "object.event": "typed_input:rejected_owner",
            "object.anomaly": "typed_input:rejected_owner",
            "object.drift": "typed_input:rejected_owner",
            "object.forecast": "typed_input:rejected_owner",
            "object.resilience-score": "typed_input:rejected_owner",
            "object.cost-anomaly": "specialist_advice:rejected_owner",
            "object.capacity-forecast": "specialist_advice:rejected_owner",
            "object.capacity-graduation-recommendation": "typed_input:rejected_owner",
            "object.arbitration-decision": "arbitration_decision:rejected_owner",
            "object.rule": "rule_state:rejected_owner",
        }
        if topic in owner_rejection_behaviors and require_topic_owner(
            self,
            topic,
            payload,
            behavior=owner_rejection_behaviors[topic],
        ):
            return
        if is_cross_vertical_candidate(topic, payload):
            await self._ingest_cross_vertical_candidate(topic, payload)
            return
        if topic == "object.change":
            await self._observe_architecture_change(payload)
            return
        if (
            topic == "object.event"
            and payload.get("event_type") == INCIDENT_INTERVENTION_EVENT_TYPE
        ):
            if payload.get("producer_principal") != "Huginn":
                raise ValueError("incident guidance requires the Huginn-owned normalized Event")
            self.record_behavior("incident_guidance:deferred")
            return
        if topic == "object.event" and str(payload.get("event_type") or "").startswith(
            "control_plane.t2_proposer_"
        ):
            self.record_behavior("t2_proposer_observation:deferred")
            return
        if topic == "object.event" and str(payload.get("event_type") or "").startswith(
            SPECIALIST_EVENT_PREFIX
        ):
            self.record_behavior("specialist_signal:deferred")
            return
        if topic == "object.event" and payload.get("event_type") == (
            "detection.readiness.observed"
        ):
            self.record_behavior("detection_readiness:observation_deferred")
            return
        if topic == "object.drift" and payload.get("kind") == "detection_readiness":
            await self._record_detection_readiness(payload)
            return
        if topic == "object.event" and payload.get("kind") == "retrospective_what_if_request":
            await self._run_retrospective_what_if(payload)
            return
        if payload.get("kind") == "document_ingestion":
            if topic == "object.event" and payload.get("event_type") == "document.received":
                await self.judge_document_ingestion(payload)
            elif topic == "object.anomaly" and payload.get("stage") == "protection_check":
                await self.judge_document_safety(payload)
            return
        if topic == "object.forecast":
            await self._judge_forecast(payload)
            return
        if topic in ("object.event", "object.anomaly", "object.drift"):
            if topic == "object.event":
                await self._attach_change_assessment(payload)
            arbitration = await self.maybe_request_arbitration(payload)
            if arbitration is not None:
                return
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            arbitration = await self._ingest_domain_signal("capacity", payload)
            if arbitration is None:
                await self._judge_capacity_forecast(payload)
        elif topic == "object.capacity-graduation-recommendation":
            await self._judge_capacity_graduation(payload)
        elif topic == "object.arbitration-decision":
            await self._record_arbitration(payload)
        elif topic == "object.rule":
            await self._record_rule_state(payload)

    async def _judge_capacity_graduation(self, payload: dict[str, Any]) -> None:
        """Issue one observation-only verdict over Freyr's shadow recommendation."""

        try:
            recommendation = CapacityGraduationRecommendation.model_validate(
                {
                    field: payload[field]
                    for field in CapacityGraduationRecommendation.model_fields
                    if field in payload
                }
            )
        except (KeyError, ValueError):
            self.record_behavior("capacity_graduation:invalid")
            return
        accepted = recommendation.status is GraduationRecommendationStatus.RECOMMEND
        verdict = {
            "kind": "capacity_graduation",
            "producer_principal": "Forseti",
            "correlation_id": str(payload.get("correlation_id") or ""),
            "idempotency_key": f"verdict:{recommendation.id}",
            "resource_id": recommendation.target_ref,
            "recommendation_id": recommendation.id,
            "transition": recommendation.transition.value,
            "target_profile": recommendation.target_profile,
            "risk_verdict": "shadow" if accepted else "deny",
            "reason": "recommendation_accepted" if accepted else "recommendation_held",
            "reason_codes": list(recommendation.reason_codes),
            "shadow_only": True,
            "execution_authority": False,
        }
        self.record_behavior("capacity_graduation:" + ("accepted" if accepted else "held"))
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)

    async def _observe_architecture_change(self, payload: dict[str, Any]) -> None:
        """Judge one planned Change through the observation-only ARB seam."""

        if self._architecture_review_loop is None:
            self.record_behavior("architecture_review:unbound")
            return
        try:
            async with asyncio.timeout(self._architecture_review_timeout_seconds):
                observation = await self._architecture_review_loop.evaluate(payload)
        except TimeoutError:
            self.record_behavior("architecture_review:timeout")
            change_id = str(payload.get("id") or payload.get("event_id") or "unknown")
            correlation_id = str(
                payload.get("correlation_id") or f"architecture-review:{change_id}"
            )
            observation = ArchitectureReviewObservation.hold(
                change_id=change_id,
                idempotency_key=str(
                    payload.get("idempotency_key") or f"architecture-review-timeout:{change_id}"
                ),
                correlation_id=correlation_id,
                target_ref=str(payload.get("target_ref") or "unknown"),
                change_digest="unknown",
                reason="observation_review_timeout",
            )
        except Exception as exc:  # noqa: BLE001 - fail closed and audit the hold
            self.record_behavior("architecture_review:failed")
            observation = ArchitectureReviewObservation.hold(
                change_id=str(payload.get("id") or payload.get("event_id") or "unknown"),
                idempotency_key=str(payload.get("idempotency_key") or "unknown"),
                correlation_id=str(payload.get("correlation_id") or "unknown"),
                target_ref=str(payload.get("target_ref") or "unknown"),
                change_digest="unknown",
                reason=f"observation_review_failed:{type(exc).__name__}",
            )
        if observation.replayed:
            self.record_behavior("architecture_review:duplicate")
            return
        self.record_behavior(f"architecture_review:{observation.recommendation}")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", observation.to_mapping())

    async def _attach_change_assessment(self, event: dict[str, Any]) -> None:
        change = event.get("normalized_change")
        if not isinstance(change, Mapping) or change.get("intent_kind") != "planned":
            return
        if self._change_assessor is None:
            event["change_assessment_status"] = "unavailable"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:unavailable")
            return
        try:
            async with asyncio.timeout(self._change_assessment_timeout_seconds):
                graph_evidence = await self._planned_change_graph_evidence(change)
            async with asyncio.timeout(self._change_assessment_timeout_seconds):
                assessment = await self._change_assessor.assess(
                    change,
                    graph_evidence=graph_evidence,
                )
        except TimeoutError:
            event["change_assessment_status"] = "failed"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:timeout")
            return
        except Exception:  # noqa: BLE001 - missing impact evidence lowers authority
            event["change_assessment_status"] = "failed"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:failed")
            return
        event["change_assessment_status"] = "review" if assessment.review_required else "clear"
        event["change_assessment"] = assessment.to_mapping()
        if assessment.review_required:
            event["human_approval_required"] = True
        self.record_behavior(f"change_assessment:{event['change_assessment_status']}")

    async def _planned_change_graph_evidence(
        self,
        change: Mapping[str, Any],
    ) -> ChangeGraphEvidenceReceipt:
        expected_release = str(change.get("ontology_release_digest") or "").strip()
        if self._operational_context is None or not expected_release:
            return ChangeGraphEvidenceReceipt.unavailable()
        occurred_at = datetime.fromisoformat(
            str(change.get("occurred_at") or "").replace("Z", "+00:00")
        )
        if occurred_at.tzinfo is None:
            raise ValueError("planned change occurred_at MUST be timezone-aware")
        snapshot = await self._operational_context.materialize(
            target_resource_id=str(change.get("target_ref") or ""),
            cutoff=occurred_at,
            catalog_versions=None,
            require_verified_links=True,
        )
        return change_graph_evidence_from_snapshot(
            snapshot,
            expected_ontology_release=expected_release,
        )

    async def _record_rule_state(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            self.record_behavior("rule_state:rejected_owner")
            return
        action_type = str(
            payload.get("action_type")
            or payload.get("remediates")
            or payload.get("action_type_id")
            or ""
        )
        state = str(payload.get("state") or payload.get("outcome") or "").strip().lower()
        if not action_type or state not in {"active", "promoted", "retired", "revoked"}:
            self.record_behavior("rule_state:invalid")
            return
        normalized = "active" if state == "promoted" else state
        incoming_revision = _rule_revision(payload.get("revision"))
        incoming_updated_at = _rule_updated_at(payload.get("updated_at"))
        incoming_source_digest = str(
            payload.get("source_digest")
            or payload.get("reviewed_package_digest")
            or payload.get("package_digest")
            or ""
        )
        current = self._rule_state.get(action_type)
        if current is not None and not _rule_state_is_newer(
            current,
            incoming_revision=incoming_revision,
            incoming_updated_at=incoming_updated_at,
            incoming_source_digest=incoming_source_digest,
        ):
            self.record_behavior("rule_state:stale")
            return
        record = {
            "state": normalized,
            "rule_id": str(payload.get("rule_id") or payload.get("id") or ""),
            "correlation_id": str(payload.get("correlation_id") or ""),
            "revision": "" if incoming_revision is None else str(incoming_revision),
            "updated_at": "" if incoming_updated_at is None else incoming_updated_at.isoformat(),
            "source_digest": incoming_source_digest,
        }
        self._rule_state.set(action_type, record)
        if self._forseti_state_store is not None:
            await self._forseti_state_store.write_state(
                f"pantheon/forseti/rule-state|{action_type}",
                {
                    "kind": "rule_state",
                    "action_type": action_type,
                    **record,
                    "recorded_at": self._now().isoformat(),
                },
            )
        self._last_owner_rule_update_at = self._now()
        self._rule_cache_stale = False
        self.record_behavior(f"rule_state:{normalized}")

    async def rehydrate(self) -> int:
        """Restore durable judgment-lowering projections before typed consumers start."""
        store = self._forseti_state_store
        if store is None:
            return 0
        restored = 0
        for prefix, target in (
            ("pantheon/forseti/detection-readiness|", self._detection_readiness),
            ("pantheon/forseti/rule-state|", self._rule_state),
        ):
            rows, total = await store.read_state_page(prefix, limit=_MAX_RESOURCES)
            if total > _MAX_RESOURCES:
                raise RuntimeError("Forseti durable projection count exceeds its bound")
            for row in rows:
                if prefix.endswith("detection-readiness|"):
                    resource_id = str(row.get("resource_id") or "")
                    if resource_id:
                        target.set(
                            resource_id,
                            {
                                "decision": str(row.get("decision") or ""),
                                "authority_ceiling": str(row.get("authority_ceiling") or ""),
                            },
                        )
                        restored += 1
                else:
                    action_type = str(row.get("action_type") or "")
                    if action_type:
                        target.set(
                            action_type,
                            {
                                "state": str(row.get("state") or ""),
                                "rule_id": str(row.get("rule_id") or ""),
                                "correlation_id": str(row.get("correlation_id") or ""),
                                "revision": str(row.get("revision") or ""),
                                "updated_at": str(row.get("updated_at") or ""),
                                "source_digest": str(row.get("source_digest") or ""),
                            },
                        )
                        restored += 1
        restored += await forseti_durability.rehydrate_arbitration_state(self)
        return restored

    async def maintenance_tick(self) -> None:
        maintenance_tick = getattr(super(), "maintenance_tick", None)
        if maintenance_tick is not None:
            await maintenance_tick()
        reference = self._last_owner_rule_update_at or self._rule_staleness_started_at
        stale = self._now() - reference > self._rule_staleness_window
        self._rule_cache_stale = stale
        if stale:
            self.record_behavior("rule_cache:stale")
        self._run_verdict_coherence_self_test()
        self._refresh_novelty_drift_signal()
        baseline_scheduler = getattr(self, "_baseline_scheduler", None)
        if baseline_scheduler is not None and baseline_scheduler.tick():
            self.record_behavior("baseline_evaluation:started")
