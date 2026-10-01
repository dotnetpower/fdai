"""Ingress runtime mixin for Huginn."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.alert_noise_wire import ALERT_NOISE_EVENT_TYPES, SignedAlertCommand

from fdai.agents._framework.huginn_dedup import HuginnDedupJournal, request_digest
from fdai.agents._framework.huginn_ingress_helpers import (
    _DISCOVERY_PROJECTOR_TIMEOUT_SECONDS,
    _MAX_FIELD_CHARS,
    _TRACE_CONTINUITY_EVENT,
    _TRACE_CONTINUITY_FIELDS,
    _UNOWNED_AUTHORITY_FIELDS,
    DiscoveryProjector,
    HuginnIngressRejected,
    HuginnIngressRejectedError,
    _bound,
    _bound_attributes,
    _bound_json,
    _change_projection,
    _copy_validated_json,
    _event_occurred_at,
    _has_control_characters,
    _kpi_measured,
    _kpi_unavailable,
    _p99_kpi,
    _ratio_kpi,
    _raw_payload_digest,
    _safe_identity,
    _safe_string,
    _validate_raw_ingress,
    _validated_operator_request_fields,
)
from fdai.agents._framework.huginn_operator_receipt import (
    OperatorRequestReceiptGate,
    ReservedOperatorRequestReceipt,
    VerifiedOperatorRequestReceipt,
)
from fdai.agents._framework.huginn_schema_learning import HuginnSchemaLearningLedger
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.case_history import OperationalCaseInput

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus


_AlertNoisePayload = Mapping[str, Any]
_AlertNoiseVerifier = Callable[[_AlertNoisePayload], object]


class HuginnIngressMixin:
    """Normalize raw source signals into Huginn-owned Event and Change objects."""

    _dedup_journal: HuginnDedupJournal | None
    _last_checkpoint_read_at: datetime | None
    _clock: Callable[[], datetime]
    _discovery_projector: DiscoveryProjector | None
    _operator_request_receipt_gate: OperatorRequestReceiptGate | None
    _schema_learning: HuginnSchemaLearningLedger | None
    _seen_keys: OrderedDict[str, None]
    _dedup_capacity: int
    _operational_case_errors: deque[str]
    _event_latency_seconds: deque[float]
    _discovery_latency_seconds: deque[float]
    _alert_noise_verifier: _AlertNoiseVerifier | None
    bus: PantheonBus | None
    _dedup_collision_decisions: int
    _dedup_correct_decisions: int
    _ingress_lock_refs: dict[str, int]
    _ingress_locks: OrderedDict[str, asyncio.Lock]

    if TYPE_CHECKING:

        def behavior_snapshot(self) -> dict[str, int]: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

    def health(self) -> dict[str, Any]:
        """Expose ingress / dedup state for Heimdall's probe."""
        checkpoint_durability = "durable" if self._dedup_journal is not None else "process_local"
        status = "ok" if self._dedup_journal is not None else "degraded"
        checkpoint_age_seconds: dict[str, Any]
        if self._last_checkpoint_read_at is None:
            checkpoint_age_seconds = _kpi_unavailable(
                "not_observed" if self._dedup_journal is not None else "not_connected",
                "checkpoint_resume_not_read",
                unit="seconds",
            )
        else:
            now = self._clock()
            checkpoint_age_seconds = _kpi_measured(
                max(0.0, (now - self._last_checkpoint_read_at).total_seconds()),
                numerator=1,
                denominator=1,
                unit="seconds",
            )
        return {
            "agent": "Huginn",
            "status": status,
            "discovery": {
                "projection": "bound" if self._discovery_projector is not None else "not_bound",
                "cursor": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_cursor_not_bound",
                    unit="seconds",
                ),
                "backpressure": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_backpressure_not_bound",
                ),
                "source_health": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_source_health_not_bound",
                ),
            },
            "checkpoint": {
                "durability": checkpoint_durability,
                "retained_cursor_source": "state_store"
                if self._dedup_journal is not None
                else None,
                "last_checkpoint_age_seconds": checkpoint_age_seconds,
            },
            "operator_request_receipts": {
                "verification": "bound"
                if self._operator_request_receipt_gate is not None
                else "fail_closed_unbound",
            },
            "schema_learning": {
                "status": "bound" if self._schema_learning is not None else "not_bound",
                "pending_fingerprints": self._schema_learning.pending_count()
                if self._schema_learning is not None
                else 0,
            },
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "operational_case_errors": list(self._operational_case_errors),
            "kpis": {
                "event_processing_latency_p99_seconds": _p99_kpi(
                    self._event_latency_seconds,
                    unit="seconds",
                    reason="no_ingest_latency_samples",
                ),
                "discovery_delivery_latency_p99_seconds": _p99_kpi(
                    self._discovery_latency_seconds,
                    unit="seconds",
                    reason="no_discovery_projection_samples",
                ),
                "dedup_accuracy": self._dedup_accuracy_kpi(),
                "schema_match_failure_rate": _ratio_kpi(
                    self.behavior_snapshot().get("raw_ingress_rejected:invalid_type", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_string", 0),
                    self.behavior_snapshot().get("ingested", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_type", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_string", 0),
                    reason="no_schema_validation_denominator",
                ),
                "discovery_cursor_lag_seconds": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_cursor_not_bound",
                    unit="seconds",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    async def ingest(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a raw source signal into an Event payload.

        Returns the normalized payload (also publishes it on the bus if
        one is bound). Duplicates by ``idempotency_key`` are dropped
        and return ``None``.
        """
        try:
            verified_operator_receipt: VerifiedOperatorRequestReceipt | None = None
            _validate_raw_ingress(raw)
            if (
                raw.get("event_type") in ALERT_NOISE_EVENT_TYPES
                or raw.get("source") == "operator-alert-noise"
            ):
                if self._alert_noise_verifier is None:
                    raise HuginnIngressRejected("alert_verifier_unavailable")
                self._alert_noise_verifier(raw)
            if raw.get("event_type") == "operator_request":
                if self._operator_request_receipt_gate is None:
                    raise HuginnIngressRejected("operator_request_receipt_unbound")
                try:
                    verified_operator_receipt = await self._operator_request_receipt_gate.verify(
                        raw
                    )
                except ValueError as exc:
                    reason = str(exc) or "invalid"
                    safe_reason = (
                        reason
                        if reason
                        in {
                            "missing",
                            "mismatch",
                            "expired",
                            "unverifiable",
                            "replayed",
                            "unknown_producer",
                            "unsigned_workflow_action",
                        }
                        else "invalid"
                    )
                    raise HuginnIngressRejected(
                        f"operator_request_receipt_{safe_reason}",
                        field="operator_request_receipt",
                    ) from exc
            if self._schema_learning is not None:
                self._schema_learning.record_accepted(raw)
            key = self._ingress_key(raw)
            async with self._key_lock(key):
                return await self._ingest_locked(
                    raw,
                    key=key,
                    verified_operator_receipt=verified_operator_receipt,
                )
        except HuginnIngressRejectedError as exc:
            if not exc.payload_digest:
                exc.payload_digest = _raw_payload_digest(raw)
            self.record_behavior(f"raw_ingress_rejected:{exc.reason_code}")
            raise

    async def maintenance_tick(self) -> None:
        maintenance_tick = getattr(super(), "maintenance_tick", None)
        if maintenance_tick is not None:
            await maintenance_tick()
        if self._schema_learning is None:
            self.record_behavior("maintenance:schema_learning_unbound")
            return
        if self.bus is None:
            self.record_behavior("maintenance:schema_learning_no_bus")
            return
        evidence = await self._schema_learning.next_evidence()
        if evidence is None:
            self.record_behavior("maintenance:schema_learning_idle")
            return
        await self.bus.publish("Huginn", "object.event", evidence.payload)
        await self._schema_learning.mark_published(evidence)
        self.record_behavior("maintenance:schema_cluster_evidence_published")

    async def ingest_operator_proposal(self, proposal: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize Bragi's authenticated in-process operator proposal."""

        try:
            _validate_raw_ingress(proposal)
            if proposal.get("event_type") != "operator_request":
                raise HuginnIngressRejected("operator_proposal_event_type", field="event_type")
            if proposal.get("operator_initiated") is not True:
                raise HuginnIngressRejected(
                    "operator_proposal_initiator", field="operator_initiated"
                )
            for field in ("initiator_principal", "action_type"):
                _safe_string(proposal.get(field), field=field, required=True)
            key = self._ingress_key(proposal)
            async with self._key_lock(key):
                return await self._ingest_locked(
                    proposal,
                    key=key,
                    trusted_operator_proposal=True,
                )
        except HuginnIngressRejectedError as exc:
            if not exc.payload_digest:
                exc.payload_digest = _raw_payload_digest(proposal)
            self.record_behavior(f"operator_proposal_rejected:{exc.reason_code}")
            raise

    async def _ingest_locked(
        self,
        raw: dict[str, Any],
        *,
        key: str,
        trusted_operator_proposal: bool = False,
        verified_operator_receipt: VerifiedOperatorRequestReceipt | None = None,
    ) -> dict[str, Any] | None:
        raw_request_digest = request_digest(raw) if self._dedup_journal is not None else ""
        if key in self._seen_keys:
            self._seen_keys.move_to_end(key)
            self.record_behavior("deduped")
            return None
        reserved_operator_receipt: ReservedOperatorRequestReceipt | None = None
        processing_started_at = self._clock()
        ingested_at = processing_started_at
        if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
            raise ValueError("Huginn clock MUST return a timezone-aware datetime")
        event_payload = raw.get("payload")
        canonical_payload = event_payload if isinstance(event_payload, Mapping) else {}
        inventory_change = canonical_payload.get("inventory_change")
        detection_readiness = canonical_payload.get("detection_readiness")
        resource_value = (
            inventory_change.get("resource") if isinstance(inventory_change, Mapping) else None
        )
        resource: Mapping[str, Any] = resource_value if isinstance(resource_value, Mapping) else {}

        event_type = _safe_identity(raw.get("event_type") or "generic", field="event_type")
        attributes = _bound_attributes(raw.get("attributes", {}))
        correlation_id = _safe_string(raw.get("correlation_id"), field="correlation_id") or key
        if event_type == "case_history.operational_case.v1":
            raw_attributes = raw.get("attributes")
            if isinstance(raw_attributes, Mapping):
                try:
                    operational_case = OperationalCaseInput.from_mapping(raw_attributes)
                    attributes = operational_case.to_mapping()
                    correlation_id = operational_case.failure_fingerprint.digest
                except (TypeError, ValueError) as exc:
                    reason = type(exc).__name__
                    self.record_behavior("operational_case:invalid")
                    self._operational_case_errors.append(reason)
        payload: dict[str, Any] = {
            "producer_principal": "Huginn",
            "correlation_id": correlation_id,
            "incident_correlation": (
                "none"
                if str(raw.get("event_type", "")).startswith("inventory.")
                else _safe_string(raw.get("incident_correlation"), field="incident_correlation")
                or "correlate"
            ),
            "idempotency_key": key,
            "event_id": _safe_string(raw.get("event_id"), field="event_id") or key,
            "source": _safe_identity(raw.get("source") or "unknown", field="source"),
            "resource_id": _bound(
                raw.get("resource_id") or raw.get("resource_ref") or resource.get("resource_id")
            ),
            "resource_type": (
                _safe_identity(
                    raw.get("resource_type") or resource.get("type"), field="resource_type"
                )
                if raw.get("resource_type") or resource.get("type")
                else None
            ),
            "event_type": event_type,
            "attributes": attributes,
            "ingested_at": ingested_at.isoformat(),
        }
        occurred_at = _event_occurred_at(raw, ingested_at=ingested_at)
        if occurred_at is not None:
            payload["occurred_at"] = occurred_at
        severity = raw.get("severity") or canonical_payload.get("severity")
        if event_type in ALERT_NOISE_EVENT_TYPES:
            signed = SignedAlertCommand.model_validate(canonical_payload.get("alert_noise"))
            if signed.command.operation != event_type or raw.get("mode") != "shadow":
                raise HuginnIngressRejected(
                    "alert_authority_mismatch",
                    field="alert_noise",
                )
            payload["alert_noise"] = signed.model_dump(mode="json")
            payload["incident_correlation"] = "none"
        if isinstance(severity, str) and severity.strip():
            payload["severity"] = _bound(severity)
        if isinstance(inventory_change, Mapping):
            payload["inventory_change"] = _bound_json(inventory_change)
            signal_kind = canonical_payload.get("signal_kind")
            if isinstance(signal_kind, str):
                payload["attributes"]["signal_kind"] = _bound(signal_kind)
        if isinstance(detection_readiness, Mapping):
            for field in (
                "dimension",
                "status",
                "observed_at",
                "expires_at",
                "source",
                "evidence_digest",
                "detail_code",
                "pass_id",
            ):
                value = detection_readiness.get(field)
                if value is not None:
                    payload["attributes"][field] = _bound(value)
        if event_type == _TRACE_CONTINUITY_EVENT and canonical_payload.get("kind") == (
            "trace_continuity"
        ):
            payload["attributes"]["trace_continuity"] = {
                field: _bound_json(canonical_payload[field], depth=1)
                for field in _TRACE_CONTINUITY_FIELDS
                if field in canonical_payload
            }
        if payload["event_type"] == "operator_request":
            payload.update(
                _validated_operator_request_fields(
                    raw,
                    channel="conversation" if trusted_operator_proposal else "ingress",
                )
            )
            stripped = _UNOWNED_AUTHORITY_FIELDS.intersection(raw)
            if stripped:
                self.record_behavior("operator_request:unowned_authority_fields_stripped")
            workflow_action = raw.get("workflow_action")
            if isinstance(workflow_action, Mapping):
                payload["workflow_action"] = _copy_validated_json(workflow_action)
        if payload["event_type"] == "human.assignment.iam_apply_requested":
            payload["attributes"]["iam_request"] = {
                field: _bound_json(canonical_payload[field])
                for field in ("case_id", "expected_revision", "ownership_digest", "ownership_ref")
                if field in canonical_payload
            }
            payload["incident_correlation"] = "none"
        if payload["event_type"] == "knowledge.handover.source_observed.v1":
            from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice

            notice = HandoverKnowledgeNotice.model_validate(canonical_payload.get("notice"))
            payload["attributes"] = {"knowledge_notice": notice.model_dump(mode="json")}
            payload["correlation_id"] = notice.source_id
            payload["incident_correlation"] = "none"
        if payload["event_type"] == "human.assignment.execution.v1":
            from fdai_service_contracts.human_access_workflow import HumanAccessWorkNotice

            access_notice = HumanAccessWorkNotice.model_validate(canonical_payload.get("notice"))
            payload["attributes"] = {"human_access_notice": access_notice.model_dump(mode="json")}
            payload["correlation_id"] = str(access_notice.request_id)
            payload["incident_correlation"] = "none"
        change_projection = _change_projection(
            raw=raw,
            canonical_payload=canonical_payload,
            event_payload=payload,
        )
        if change_projection is not None:
            payload["normalized_change"] = dict(change_projection)
        if self._dedup_journal is not None:
            try:
                claim = await self._dedup_journal.claim(
                    idempotency_key=key,
                    request_digest=raw_request_digest,
                    payload=payload,
                    change_projection=change_projection,
                )
            except ValueError:
                self._dedup_collision_decisions += 1
                self.record_behavior("dedup:key_collision")
                raise
            if claim.duplicate:
                self._remember_key(key)
                self._dedup_correct_decisions += 1
                self.record_behavior("deduped")
                return None
            payload = claim.payload
            change_projection = claim.change_projection
            published_topics = claim.published_topics
        else:
            published_topics = frozenset()
        if verified_operator_receipt is not None:
            if self._operator_request_receipt_gate is None:
                raise HuginnIngressRejected("operator_request_receipt_unbound")
            try:
                reserved_operator_receipt = await self._operator_request_receipt_gate.reserve(
                    verified_operator_receipt
                )
            except ValueError as exc:
                reason = str(exc) or "invalid"
                safe_reason = reason if reason in {"expired", "replayed"} else "invalid"
                raise HuginnIngressRejected(
                    f"operator_request_receipt_{safe_reason}",
                    field="operator_request_receipt",
                ) from exc
        # Measurable behaviour: the sensing layer's ingest / dedup rates, so a
        # scenario can see an ingress flood (the flooding concern one layer up
        # from the judge). Recorded on the decision to emit, before publish.
        self.record_behavior("ingested")
        if self._dedup_journal is not None:
            self._dedup_correct_decisions += 1
        if "inventory_change" in payload and self._discovery_projector is not None:
            try:
                discovery_started_at = self._clock()
                async with asyncio.timeout(_DISCOVERY_PROJECTOR_TIMEOUT_SECONDS):
                    await self._discovery_projector(payload)
                self._record_latency(self._discovery_latency_seconds, discovery_started_at)
                self.record_behavior("discovery_projected")
            except TimeoutError:
                self.record_behavior("discovery_projection:timeout")
                raise
            except asyncio.CancelledError:
                self.record_behavior("discovery_projection:cancelled")
                raise
            except Exception:
                self.record_behavior("discovery_projection_failed")
                raise
        publish_cancelled = False
        try:
            if self.bus is not None:
                publish_cancelled = await self._publish_event_change(
                    payload,
                    change_projection,
                    idempotency_key=key,
                    request_digest=raw_request_digest,
                    published_topics=published_topics,
                )
            elif self._dedup_journal is not None:
                if reserved_operator_receipt is not None:
                    if self._operator_request_receipt_gate is None:
                        raise HuginnIngressRejected("operator_request_receipt_unbound")
                    await self._operator_request_receipt_gate.release(reserved_operator_receipt)
                self.record_behavior("ingress_publication:unavailable")
                return payload
            if self._dedup_journal is not None:
                complete_task = asyncio.create_task(
                    self._dedup_journal.complete(
                        idempotency_key=key,
                        request_digest=raw_request_digest,
                        require_published_topics=self.bus is not None,
                    )
                )
                try:
                    await asyncio.shield(complete_task)
                except asyncio.CancelledError:
                    await complete_task
                    self.record_behavior("dedup_completion:cancelled")
                    publish_cancelled = True
        except Exception:
            if (
                reserved_operator_receipt is not None
                and self._operator_request_receipt_gate is not None
            ):
                await self._operator_request_receipt_gate.release(reserved_operator_receipt)
            raise
        if reserved_operator_receipt is not None:
            if self._operator_request_receipt_gate is None:
                raise HuginnIngressRejected("operator_request_receipt_unbound")
            try:
                await self._operator_request_receipt_gate.finalize(reserved_operator_receipt)
            except ValueError as exc:
                reason = str(exc) or "invalid"
                safe_reason = reason if reason in {"expired", "replayed"} else "invalid"
                raise HuginnIngressRejected(
                    f"operator_request_receipt_{safe_reason}",
                    field="operator_request_receipt",
                ) from exc
        self._remember_key(key)
        self._record_latency(self._event_latency_seconds, processing_started_at)
        if publish_cancelled:
            raise asyncio.CancelledError
        return payload

    def _record_latency(self, target: deque[float], started_at: datetime) -> None:
        ended_at = self._clock()
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("Huginn clock MUST return a timezone-aware datetime")
        target.append(max(0.0, (ended_at - started_at).total_seconds()))

    def _dedup_accuracy_kpi(self) -> dict[str, Any]:
        total = self._dedup_correct_decisions + self._dedup_collision_decisions
        if total == 0:
            return _kpi_unavailable("not_measured", "no_authoritative_dedup_decisions")
        return _kpi_measured(
            self._dedup_correct_decisions / total,
            numerator=self._dedup_correct_decisions,
            denominator=total,
            unit="ratio",
        )

    async def _publish_event_change(
        self,
        payload: Mapping[str, Any],
        change_projection: Mapping[str, Any] | None,
        *,
        idempotency_key: str,
        request_digest: str,
        published_topics: frozenset[str],
    ) -> bool:
        if self.bus is None:
            return False
        cancelled = False
        if "object.event" not in published_topics:
            event_task = asyncio.create_task(
                self.bus.publish("Huginn", "object.event", dict(payload))
            )
            try:
                await asyncio.shield(event_task)
            except asyncio.CancelledError:
                await event_task
                self.record_behavior("event_publication:cancelled")
                cancelled = True
            if self._dedup_journal is not None:
                await self._dedup_journal.mark_published(
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    topic="object.event",
                )
        if change_projection is not None:
            if "object.change" not in published_topics:
                change_task = asyncio.create_task(
                    self.bus.publish("Huginn", "object.change", dict(change_projection))
                )
                try:
                    await asyncio.shield(change_task)
                except asyncio.CancelledError:
                    await change_task
                    self.record_behavior("change_publication:cancelled")
                    cancelled = True
                if self._dedup_journal is not None:
                    await self._dedup_journal.mark_published(
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        topic="object.change",
                    )
        return cancelled

    @asynccontextmanager
    async def _key_lock(self, key: str) -> AsyncIterator[None]:
        lock = self._lock_for_key(key)
        self._ingress_lock_refs[key] = self._ingress_lock_refs.get(key, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._ingress_lock_refs.get(key, 1) - 1
            if remaining > 0:
                self._ingress_lock_refs[key] = remaining
            else:
                self._ingress_lock_refs.pop(key, None)
                self._ingress_locks.pop(key, None)

    def _lock_for_key(self, key: str) -> asyncio.Lock:
        lock = self._ingress_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._ingress_locks[key] = lock
        self._ingress_locks.move_to_end(key)
        retained_count = sum(self._ingress_lock_refs.values())
        while len(self._ingress_locks) > self._dedup_capacity + retained_count:
            for old_key, old_lock in tuple(self._ingress_locks.items()):
                if not old_lock.locked() and old_key not in self._ingress_lock_refs:
                    self._ingress_locks.pop(old_key, None)
                    break
            else:
                break
        return lock

    def _ingress_key(self, raw: Mapping[str, Any]) -> str:
        for field in ("idempotency_key", "id", "event_id"):
            provided = raw.get(field)
            if provided in (None, ""):
                continue
            if not isinstance(provided, str):
                raise HuginnIngressRejected("invalid_idempotency_key", field=field)
            normalized = provided.strip()
            if (
                not normalized
                or len(normalized) > _MAX_FIELD_CHARS
                or _has_control_characters(normalized)
            ):
                raise HuginnIngressRejected("invalid_idempotency_key", field=field)
            return normalized
        event_type = _safe_identity(raw.get("event_type") or "generic", field="event_type")
        source = _safe_identity(raw.get("source") or "unknown", field="source")
        resource = (
            _safe_string(
                raw.get("resource_id") or raw.get("resource_ref") or "",
                field="resource_id",
            )
            or ""
        )
        time_value = raw.get("occurred_at") or raw.get("detected_at") or raw.get("created_at") or ""
        time_basis = (
            time_value.isoformat()
            if isinstance(time_value, datetime)
            else (_safe_string(time_value, field="occurred_at") or "")
        )
        attributes = _bound_attributes(raw.get("attributes", {}))
        if not any((event_type, source, resource, time_basis, attributes)):
            raise HuginnIngressRejected("missing_stable_identity")
        return stable_idempotency_key(
            "huginn-event",
            event_type,
            source,
            resource,
            time_basis,
            attributes,
        )

    def _remember_key(self, key: str) -> None:
        self._seen_keys[key] = None
        self._seen_keys.move_to_end(key)
        if len(self._seen_keys) > self._dedup_capacity:
            self._seen_keys.popitem(last=False)


__all__ = ["HuginnIngressMixin"]
