"""Owners record explicit operational evidence classes; only unavailable keeps generic holds.

Mimir (governance; owns Rule, Policy, and rule-generation builds; publishes ``object.policy``)
and Forseti (pipeline judge; publishes ``object.verdict``) are exercised through their declared
topics and judgment path. Issuance is a bounded provider call, never an agent call, and no
agent gains a topic, an owned object, or execution authority.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.core.operational_context.test_context import TestContextClaim as ContextClaim
from fdai.core.operational_context.test_context_commands import (
    TestContextCommandHandler as ContextCommandHandler,
)
from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
from fdai.core.operational_evidence.owner_outcome import (
    OperationalEvidenceRejectedError,
    OperationalEvidenceRequester,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
    OperationalEvidenceRejectionRecord,
)

from tests.core.operational_context.test_test_context import NOW


class _Verifier:
    """Stand-in verifier that records one attempt-scoped rejection for chosen purposes."""

    def __init__(self, rejected: dict[str, OperationalEvidenceRejectionClass]) -> None:
        self._rejected = rejected
        self.records: dict[str, OperationalEvidenceRejectionRecord] = {}

    async def issue(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse:
        rejection_class = self._rejected.get(request.lookup.purpose_id)
        if rejection_class is None:
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        record = OperationalEvidenceRejectionRecord.create(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            purpose_id=request.lookup.purpose_id,
            rejection_class=rejection_class,
            reason_codes=("grant_revoked",),
            trust_registry_pin="sha256:" + "1" * 64,
            grant_registry_pin="sha256:" + "2" * 64,
            verifier_id="operational-evidence-verifier",
            verifier_version="1.0.0",
            recorded_at=NOW,
        )
        self.records[record.record_digest] = record
        return OperationalEvidenceIssuanceResponse(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            status=OperationalEvidenceIssuanceStatus.REJECTED,
            record_digest=record.record_digest,
        )

    async def outcome(
        self, response: OperationalEvidenceIssuanceResponse, *, lookup: OperationalEvidenceLookup
    ) -> OperationalEvidenceRejectionRecord | None:
        return self.records.get(str(response.record_digest))


def _requester(verifier: _Verifier) -> OperationalEvidenceRequester:
    return OperationalEvidenceRequester(
        issuer=verifier,
        outcomes=verifier,
        producer_id="core-control-plane",
        producer_version="1.0.0",
    )


class _NoAdmission:
    async def admit(self, **_values: str) -> None:
        return None


async def test_mimir_refuses_a_revoked_command_with_its_class_and_publishes_no_policy() -> None:
    verifier = _Verifier(
        {"operator-test-context-command": OperationalEvidenceRejectionClass.REVOKED}
    )
    requester = _requester(verifier)
    store = InMemoryStateStore()
    handler = ContextCommandHandler(
        contexts=GovernedTestContextStore(
            store=store, admission=_NoAdmission(), evidence=requester, clock=lambda: NOW
        ),
        admission=_NoAdmission(),
        evidence=requester,
        clock=lambda: NOW,
    )
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    huginn, mimir = Huginn(), Mimir()
    mimir.bind_test_context_commands(handler)
    for agent in (huginn, mimir):
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    request = {
        "operation": "propose",
        "context_id": "test-example",
        "access_scope_digest": "a" * 64,
        "target_ref": "resource-example",
        "signal_code": "cpu_percent",
        "expected_revision": 0,
        "policy_revision": "policy:example:1",
        "source_ref": "operator-turn:example",
        "semantic_receipt": "sha256:" + "a" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": NOW.isoformat(),
        "effective_to": (NOW + timedelta(hours=1)).isoformat(),
    }
    with pytest.raises(OperationalEvidenceRejectedError, match="operational_evidence_revoked"):
        await huginn.ingest(
            {
                "id": "propose-example",
                "event_id": "propose-example",
                "idempotency_key": "propose-example",
                "correlation_id": "propose-example",
                "source": "operator-context-command",
                "event_type": "test_context.command.v1",
                "attributes": {
                    "request": request,
                    "actor_id": "operator-one",
                    "actor_roles": ["Contributor"],
                    "idempotency_key": "propose-example",
                    "requested_at": NOW.isoformat(),
                },
            }
        )
    assert bus.messages_on("object.policy") == []
    assert len(verifier.records) == 1


def _claim() -> ContextClaim:
    return ContextClaim(
        context_id="test-example",
        revision=2,
        access_scope_digest="a" * 64,
        target_ref="resource-example",
        signal_code="cpu_percent",
        expected_min=60,
        expected_max=90,
        effective_from=NOW - timedelta(minutes=5),
        effective_to=NOW + timedelta(hours=1),
        recorded_at=NOW - timedelta(minutes=4),
        source_ref="operator-turn:example",
        requested_by="operator-one",
        reviewed_by="reviewer-two",
        policy_revision="policy:example:1",
        state="reviewed",
    )


async def test_forseti_names_the_observation_class_and_keeps_generic_hold_when_unavailable() -> (
    None
):
    claim = _claim()

    class _Source:
        async def read(self, **_kwargs: Any) -> ContextClaim:
            return claim

    class _ClaimOnly:
        async def admit(self, **values: str) -> DecisionEvidenceAdmission | None:
            if values["purpose_id"] == "operational-test-observation":
                return None
            return DecisionEvidenceAdmission(
                receipt_digest="sha256:" + "b" * 64,
                verification_bundle_digest="sha256:" + "c" * 64,
                verified_at=NOW,
                valid_until=claim.effective_to,
                **values,
            )

    event = {
        "event_type": "restart_needed",
        "correlation_id": "test-context-example",
        "resource_id": "resource-example",
        "access_scope_digest": "a" * 64,
        "detected_at": NOW.isoformat(),
        "metric": "cpu_percent",
        "observed_value": 80.0,
        "service_impact": "none",
        "protected_signal": False,
    }
    forseti = Forseti(
        test_context_source=_Source(),
        test_context_admission=_ClaimOnly(),
        test_context_clock=lambda: NOW,
    )
    generic = await forseti.judge(event)
    assert generic is not None
    assert generic["test_context"]["reason"] == "observation_admission_required"
    forseti.bind_test_context_evidence(
        _requester(
            _Verifier({"operational-test-observation": OperationalEvidenceRejectionClass.PARTIAL})
        )
    )
    classified = await forseti.judge(event)
    assert classified is not None
    assert classified["risk_verdict"] == "hil"
    assert classified["test_context"]["reason"] == "operational_evidence_partial"
    assert classified["resolved_autonomy_ceiling"] == "shadow_only"
