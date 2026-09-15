"""Agent-invoked alert assessment/plan handling with durable outbox and replay."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    NoiseAssessment,
    NoisePolicy,
    digest_record,
)
from fdai_service_contracts.alert_noise_codec import ALERT_RESULT_WIRE_BYTES
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.alert_noise_projection import AlertProposalDetail
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    AlertNoiseResult,
    SignedAlertCommand,
    SignedAlertResult,
    sign_alert_record,
    validate_alert_ingress,
    verify_alert_record,
)

from fdai.core.detection.alert_noise import AlertPlanHeld, assess_alert_noise, plan_alert_change
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.delivery.alert_noise_codecs import COMMAND_CONSUMER_V1, RESULT_PRODUCER_V1
from fdai.delivery.alert_noise_evidence import StateStoreAlertEvaluationReader
from fdai.delivery.alert_noise_projection import alert_proposal_detail
from fdai.shared.providers.alert_noise import (
    AlertEvidenceSource,
    AlertPeriodEvidenceSource,
    AlertPlanArtifacts,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


class AlertNoiseAgentHandler:
    """Separate Heimdall observation from Forseti planning; never call an executor."""

    def __init__(
        self,
        *,
        store: StateStore,
        sources: Mapping[str, AlertEvidenceSource],
        principals: Mapping[str, frozenset[str]],
        policy: NoisePolicy,
        transport_key: bytes,
        workflows: AlertWorkflowCoordinator | None = None,
        evaluations: Mapping[str, StateStoreAlertEvaluationReader] | None = None,
        artifacts: AlertPlanArtifacts | None = None,
        ready: Callable[[], bool] = lambda: True,
        effect_tick: Callable[[], Awaitable[int]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.sources, self.principals = store, dict(sources), dict(principals)
        self.policy, self.clock = policy, clock
        if len(transport_key) < 32:
            raise ValueError("alert transport key MUST contain at least 32 bytes")
        self.transport_key = transport_key
        self.workflows, self.evaluations = workflows, dict(evaluations or {})
        self.artifacts = artifacts
        self.ready = ready
        self.effect_tick = effect_tick

    def verify_ingress(self, raw: Mapping[str, Any]) -> SignedAlertCommand:
        """Authenticate exact outer routing before either ingress path deduplicates it."""
        signed = validate_alert_ingress(raw, self.transport_key)
        COMMAND_CONSUMER_V1.decode_mapping(signed.model_dump(mode="json"))
        return signed

    async def observe(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Heimdall records bounded evidence and returns one no-authority Drift payload."""
        signed = SignedAlertCommand.model_validate(payload.get("alert_noise"))
        verify_alert_record(signed.command, signed.signature, self.transport_key)
        command = signed.command
        if payload.get("producer_principal") != "Huginn":
            raise ValueError("alert observation requires authenticated Huginn ingress")
        key = "alert-noise:observation:" + command.request_ref
        existing = await self.store.read_state(key)
        if existing is not None:
            if existing.get("command_digest") != digest_record(command):
                raise ValueError("alert observation request identity conflict")
            return dict(existing)
        now = self.clock()
        reason: str | None = None
        evidence: AlertEvidence | None = None
        if not command.requested_at <= now < command.expires_at:
            reason = "request_expired"
        elif command.scope_ref not in self.principals.get(command.requester_ref, frozenset()):
            reason = "scope_denied"
        elif command.operation == "alert_noise.propose":
            retained = await self.store.read_state(
                "alert-noise:evidence:" + str(command.evidence_digest)
            )
            if retained is None:
                reason = "evidence_not_retained"
            else:
                evidence = AlertEvidence.model_validate(retained)
        else:
            source = self.sources.get(command.scope_ref)
            if source is None:
                reason = "source_unavailable"
            else:
                try:
                    async with asyncio.timeout(65):
                        if command.period_seconds is None:
                            evidence = await source.collect(now=now)
                        elif isinstance(source, AlertPeriodEvidenceSource):
                            evidence = await source.collect_period(
                                now=now, period_seconds=command.period_seconds
                            )
                            if (
                                evidence.window_end != now
                                or (evidence.window_end - evidence.window_start).total_seconds()
                                != command.period_seconds
                            ):
                                raise ValueError("alert source returned a different period")
                        else:
                            reason = "period_source_unavailable"
                except (ValueError, RuntimeError, TimeoutError):
                    evidence = None
                    reason = "source_unavailable"
        evidence_digest: str | None = None
        if evidence is not None:
            if evidence.stamp.scope_ref != command.scope_ref:
                raise ValueError("alert source scope mismatch")
            evidence_digest = digest_record(evidence)
            if command.evidence_digest is not None and command.evidence_digest != evidence_digest:
                raise ValueError("alert retained evidence digest mismatch")
            if evidence.stamp.synthetic:
                reason = "synthetic_live_evidence"
            else:
                await self._retain(
                    "alert-noise:evidence:" + evidence_digest,
                    evidence.model_dump(mode="json"),
                    "Heimdall",
                )
        signal: dict[str, Any] = {
            "kind": "alert_noise",
            "correlation_id": command.request_ref,
            "idempotency_key": "alert-noise:observed:" + command.request_ref,
            "resource_id": command.scope_ref,
            "command": command.model_dump(mode="json"),
            "command_digest": digest_record(command),
            "evidence_digest": evidence_digest,
            "reason": reason,
            "execution_authority": False,
        }
        await self._retain(key, signal, "Heimdall")
        return signal

    async def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Forseti turns only Heimdall's retained evidence into a replayable result."""
        if payload.get("producer_principal") != "Heimdall" or payload.get("kind") != "alert_noise":
            raise ValueError("alert planning requires authenticated Heimdall evidence")
        command = AlertNoiseCommand.model_validate(payload.get("command"))
        retained = await self.store.read_state("alert-noise:observation:" + command.request_ref)
        if retained is None or any(payload.get(key) != value for key, value in retained.items()):
            raise ValueError("alert observation lineage mismatch")
        result_key = "alert-noise:result:" + command.request_ref
        existing = await self.store.read_state(result_key)
        if existing is not None:
            result = AlertNoiseResult.model_validate(existing["result"])
            if result.command != command:
                raise ValueError("alert result identity conflict")
            return result.model_dump(mode="json")
        now = self.clock()
        reason = retained.get("reason")
        try:
            now = self._request_now(command)
        except AlertPlanHeld as exc:
            reason = str(exc)
        report: NoiseAssessment | None = None
        plan: AlertChangePlan | None = None
        detail: AlertProposalDetail | None = None
        status = "held"
        evidence_digest = retained.get("evidence_digest")
        if reason is None and isinstance(evidence_digest, str):
            raw = await self.store.read_state("alert-noise:evidence:" + evidence_digest)
            if raw is None:
                raise ValueError("alert evidence disappeared")
            evidence = AlertEvidence.model_validate(raw)
            report = assess_alert_noise(evidence, policy=self.policy, now=now)
            status = "assessment_ready"
            if command.operation == "alert_noise.propose":
                if command.treatment is None:
                    raise ValueError("alert proposal treatment missing")
                try:
                    reader = self.evaluations.get(command.scope_ref)
                    comparison = (
                        await reader.read(evidence=evidence, treatment=command.treatment, now=now)
                        if reader is not None
                        else None
                    )
                    plan = plan_alert_change(
                        evidence,
                        command.treatment,
                        policy=self.policy,
                        requester_ref=command.requester_ref,
                        now=self._request_now(command),
                        evaluation_receipt=comparison,
                    )
                    await self._retain(
                        "alert-noise:plan:" + digest_record(plan),
                        plan.model_dump(mode="json"),
                        "Forseti",
                    )
                    self._request_now(command)
                    if self.artifacts is not None:
                        await self.artifacts.prepare(plan=plan, evidence=evidence)
                    self._request_now(command)
                    workflow = (
                        await self.workflows.run(
                            plan_digest=digest_record(plan),
                            evidence_digest=plan.evidence_digest,
                            correlation_id=command.request_ref,
                        )
                        if self.workflows is not None
                        else None
                    )
                    detail = alert_proposal_detail(
                        plan, evidence, comparison, workflow, now=self._request_now(command)
                    )
                    status = "proposal_ready"
                except (AlertPlanHeld, AlertExecutionHeld) as exc:
                    status, reason, plan = "held", str(exc), None
        try:
            self._request_now(command)
        except AlertPlanHeld as exc:
            status, reason, plan = "held", str(exc), None
        now = self.clock()
        result = AlertNoiseResult.model_validate(
            {
                "command": command,
                "command_digest": digest_record(command),
                "recorded_at": now,
                "status": status,
                "reason": reason or ("evidence_unavailable" if status == "held" else None),
                "assessment": report,
                "plan": plan,
                "detail": detail if plan is not None else None,
            }
        )
        await self._retain(
            result_key,
            {
                "result": result.model_dump(mode="json"),
                "publication_state": "pending",
                "revision": 1,
            },
            "Forseti",
        )
        return result.model_dump(mode="json")

    def _request_now(self, command: AlertNoiseCommand) -> datetime:
        """Recheck current scope and the trusted clock after I/O and before a new handoff."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise AlertPlanHeld("clock_invalid")
        if not command.requested_at <= now < command.expires_at:
            raise AlertPlanHeld("request_expired")
        if command.scope_ref not in self.principals.get(command.requester_ref, frozenset()):
            raise AlertPlanHeld("scope_denied")
        return now

    async def _retain(self, key: str, value: Mapping[str, Any], actor: str) -> None:
        created = await self.store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "alert_noise.recorded",
                "actor": actor,
                "correlation_id": str(value.get("correlation_id", key)),
                "record_ref": key,
                "execution_authority": False,
            },
        )
        if not created and await self.store.read_state(key) != value:
            raise ValueError("alert immutable evidence conflict")


async def publish_alert_noise_results(
    *, handler: AlertNoiseAgentHandler, bus: EventBus, stop: asyncio.Event, topic: str
) -> None:
    """Drain durable results at least once; duplicate delivery is safe at the consumer."""
    while not stop.is_set():
        await drain_alert_noise_results(handler=handler, bus=bus, topic=topic)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            continue


async def drain_alert_noise_results(
    *, handler: AlertNoiseAgentHandler, bus: EventBus, topic: str
) -> int:
    """Publish the oldest pending page; a busy scope cannot starve retained older results."""
    _, total = await handler.store.read_state_page(
        "alert-noise:result:", limit=1, field="publication_state", value="pending"
    )
    rows, _ = await handler.store.read_state_page(
        "alert-noise:result:",
        limit=100,
        offset=max(0, total - 100),
        field="publication_state",
        value="pending",
    )
    published = 0
    for row in reversed(rows):
        result = AlertNoiseResult.model_validate(row["result"])
        signed = SignedAlertResult(
            result=result, signature=sign_alert_record(result, handler.transport_key)
        )
        payload = signed.model_dump(mode="json")
        if len(signed.model_dump_json().encode()) > ALERT_RESULT_WIRE_BYTES:
            # Publish an explicit terminal hold, never truncate a scope or loop on poison data.
            result = AlertNoiseResult(
                command=result.command,
                command_digest=result.command_digest,
                recorded_at=result.recorded_at,
                status="held",
                reason="result_byte_limit",
            )
            signed = SignedAlertResult(
                result=result, signature=sign_alert_record(result, handler.transport_key)
            )
            payload = signed.model_dump(mode="json")
        payload = RESULT_PRODUCER_V1.encode_mapping(payload)
        async with asyncio.timeout(15):
            await bus.publish(topic, result.command.request_ref, payload)
        changed = await handler.store.compare_and_set_state_with_audit(
            "alert-noise:result:" + result.command.request_ref,
            {**row, "publication_state": "published", "revision": int(row["revision"]) + 1},
            expected_revision=int(row["revision"]),
            audit_entry={
                "actor": "Forseti",
                "action_kind": "alert_noise.result.published",
                "correlation_id": result.command.request_ref,
                "result_digest": digest_record(result),
            },
        )
        published += int(changed)
    return published
