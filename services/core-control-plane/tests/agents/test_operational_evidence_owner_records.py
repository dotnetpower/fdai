"""Every remaining owner records the verifier's explicit class and cites its rejection record.

Thor (sole executor; owns ActionRun on ``object.action-run``) holds dispatch, Mimir (rule and
policy steward on ``object.policy``) audits a refused transition, Heimdall (observer; owns
ForecastOutcome on ``object.forecast-outcome``) excludes scoring in schema ``1.2.0``, the T1 reuse
tier names the class in its reason codes, and the Pattern read fails with it. Only an
``unavailable`` attempt keeps each generic reason. Issuance stays a bounded provider call; no
agent gains a topic, an owned object, or execution or promotion authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.core.detection.forecast_context import ContextualForecastObservationProvider
from fdai.core.detection.forecast_outcome import close_forecast
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_context.test_context_commands import (
    TestContextCommandHandler as ContextCommandHandler,
)
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchBinding as DispatchBinding,
)
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchGuard as DispatchGuard,
)
from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
from fdai.core.operational_evidence.owner_outcome import (
    OperationalEvidenceAttempt,
    OperationalEvidenceRejectedError,
    OperationalEvidenceRequester,
)
from fdai.core.tiers.t1_lightweight import T1Outcome
from fdai.delivery.azure.operational_evidence import AzureCurrentReuseVerifier
from fdai.delivery.persistence.postgres_forecast_episode import _observation_mapping
from fdai.delivery.persistence.state_store_forecast_context import (
    StateStoreForecastContextProvider,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
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

from tests.agents.test_operational_evidence_owners import _claim as _reviewed_claim
from tests.core.detection.test_forecast_context import _Context, _evidence, _Metrics
from tests.core.detection.test_forecast_episode import _episode
from tests.core.detection.test_forecast_outcome import T0, _expectation
from tests.core.operational_context.test_test_context import NOW, _claim, _TransitionAdmission
from tests.core.tiers.t1_lightweight.test_contextual_reuse import _tier
from tests.core.tiers.t1_lightweight.test_contextual_reuse import _Verifier as _ReuseVerifier
from tests.delivery.azure.test_operational_evidence import (
    _action,
    _clock,
    _context,
    _event,
    _Safety,
    _Snapshots,
)
from tests.persistence.test_state_store_forecast_context import _record

_R = OperationalEvidenceRejectionClass
_SLICES = ("actions", "changes", "resource_lifecycle", "excluded_windows")


class _ClassVerifier:
    """Stand-in verifier that records one attempt-scoped rejection for chosen purposes."""

    def __init__(self, rejected: Mapping[str, OperationalEvidenceRejectionClass]) -> None:
        self._rejected = dict(rejected)
        self.records: dict[str, OperationalEvidenceRejectionRecord] = {}
        self.requests: list[OperationalEvidenceIssuanceRequest] = []

    async def issue(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse:
        self.requests.append(request)
        rejection_class = self._rejected.get(request.lookup.purpose_id)
        if rejection_class is None:
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        conflicting = rejection_class is _R.CONFLICTING
        record = OperationalEvidenceRejectionRecord.create(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            purpose_id=request.lookup.purpose_id,
            rejection_class=rejection_class,
            reason_codes=("source_disagreement",) if conflicting else ("grant_revoked",),
            conflict_evidence_digests=("sha256:" + "7" * 64,) if conflicting else (),
            trust_registry_pin="sha256:" + "1" * 64,
            grant_registry_pin="sha256:" + "2" * 64,
            verifier_id="operational-evidence-verifier",
            verifier_version="1.0.0",
            recorded_at=request.requested_at,
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

    @property
    def purposes(self) -> list[str]:
        return [request.lookup.purpose_id for request in self.requests]

    @property
    def digest(self) -> str:
        (only,) = self.records
        return only


def _requester(verifier: _ClassVerifier) -> OperationalEvidenceRequester:
    return OperationalEvidenceRequester(
        issuer=verifier,
        outcomes=verifier,
        producer_id="core-control-plane",
        producer_version="1.0.0",
    )


class _NoAdmission:
    async def admit(self, **_values: str) -> None:
        return None


def _attempt(rejection_class: OperationalEvidenceRejectionClass) -> OperationalEvidenceAttempt:
    record = OperationalEvidenceRejectionRecord.create(
        attempt_id="a" * 32,
        lookup_digest="sha256:" + "3" * 64,
        purpose_id="current-case-reuse",
        rejection_class=rejection_class,
        reason_codes=("grant_revoked",),
        trust_registry_pin="sha256:" + "1" * 64,
        grant_registry_pin="sha256:" + "2" * 64,
        verifier_id="operational-evidence-verifier",
        verifier_version="1.0.0",
        recorded_at=NOW,
    )
    return OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.REJECTED, record)


@pytest.mark.parametrize("rejected", [_R.CONFLICTING, None])
async def test_thor_dispatch_hold_names_the_class_and_cites_the_rejection(
    rejected: OperationalEvidenceRejectionClass | None,
) -> None:
    claim = _claim()
    source = AsyncMock()
    source.read.return_value = claim
    verifier = _ClassVerifier({"operational-test-context": rejected} if rejected else {})
    invoked = AsyncMock(return_value=True)
    thor = Thor(executor=invoked, clock=lambda: NOW)
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    thor.bind_bus(bus)
    thor.bind_test_context_dispatch_guard(
        DispatchGuard(
            source=source,
            admission=_NoAdmission(),
            clock=lambda: NOW,
            evidence=_requester(verifier),
        )
    )
    run = ActionRun(
        correlation_id="queued-context-action",
        action_type="ops.restart-service",
        resource_id=claim.target_ref,
        state=ActionRunState.VERDICTED,
        verdict="auto",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
        test_context_guard=DispatchBinding(
            target_ref=claim.target_ref,
            access_scope_digest=claim.access_scope_digest,
            signal_code=claim.signal_code,
            context_digest=claim.digest,
        ),
    )
    await thor._execute(run)
    invoked.assert_not_awaited()
    assert verifier.purposes == ["operational-test-context"]
    published = bus.messages_on("object.action-run")[-1].payload
    assert run.state is ActionRunState.DENY_DROPPED
    if rejected is None:
        assert run.outcome == "test_context_changed_before_dispatch"
        assert run.evidence_rejection_ref is None
        assert "evidence_rejection_ref" not in published
        return
    assert run.outcome == "operational_evidence_conflicting"
    assert run.evidence_rejection_ref == verifier.digest
    assert published["outcome"] == "operational_evidence_conflicting"
    assert published["evidence_rejection_ref"] == verifier.digest
    assert ActionRun.from_dict(run.to_dict()).evidence_rejection_ref == verifier.digest
    with pytest.raises(ValueError, match="rejection reference"):
        ActionRun.from_dict({**run.to_dict(), "evidence_rejection_ref": "forged"})


def _refusals(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "test_context.transition_refused"
    ]


def _proposal() -> dict[str, Any]:
    claim = _claim()
    return {
        "operation": "propose",
        "context_id": claim.context_id,
        "access_scope_digest": claim.access_scope_digest,
        "target_ref": claim.target_ref,
        "signal_code": claim.signal_code,
        "expected_revision": 0,
        "policy_revision": claim.policy_revision,
        "source_ref": claim.source_ref,
        "semantic_receipt": "sha256:" + "a" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": NOW.isoformat(),
        "effective_to": (NOW + timedelta(hours=1)).isoformat(),
    }


async def test_mimir_audits_a_refused_command_through_its_topic_path() -> None:
    verifier = _ClassVerifier({"operator-test-context-command": _R.REVOKED})
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
    with pytest.raises(OperationalEvidenceRejectedError) as refused:
        await huginn.ingest(
            {
                "id": "propose-example",
                "event_id": "propose-example",
                "idempotency_key": "propose-example",
                "correlation_id": "propose-example",
                "source": "operator-context-command",
                "event_type": "test_context.command.v1",
                "attributes": {
                    "request": _proposal(),
                    "actor_id": "operator-one",
                    "actor_roles": ["Contributor"],
                    "idempotency_key": "propose-example",
                    "requested_at": NOW.isoformat(),
                },
            }
        )
    assert "operational_evidence_revoked" in str(refused.value)
    assert verifier.digest in str(refused.value)
    assert bus.messages_on("object.policy") == []
    (entry,) = _refusals(store)
    assert entry["owner_agent"] == "Mimir"
    assert entry["purpose_id"] == "operator-test-context-command"
    assert entry["rejection_class"] == "revoked"
    assert entry["rejection_ref"] == verifier.digest
    assert entry["correlation_id"] == "propose-example"
    assert entry["execution_authority"] is False and entry["promotion_authority"] is False
    assert "context_digest" not in entry
    assert await store.read_state("test-context-target:v1:" + "0" * 64) is None


@pytest.mark.parametrize("rejected", [_R.STALE, None])
async def test_mimir_audits_a_refused_transition_and_changes_no_state(
    rejected: OperationalEvidenceRejectionClass | None,
) -> None:
    verifier = _ClassVerifier({"test-context-transition": rejected} if rejected else {})
    requester = _requester(verifier)
    store = InMemoryStateStore()
    handler = ContextCommandHandler(
        contexts=GovernedTestContextStore(
            store=store, admission=_NoAdmission(), evidence=requester, clock=lambda: NOW
        ),
        admission=_TransitionAdmission(),
        evidence=requester,
        clock=lambda: NOW,
    )
    command = {
        "request": _proposal(),
        "actor_id": "operator-one",
        "actor_roles": ["Contributor"],
        "idempotency_key": "propose-example",
        "requested_at": NOW.isoformat(),
    }
    with pytest.raises(PermissionError) as refused:
        await handler.transition(command, reviewed_by_var=False)
    assert "test-context-transition" in verifier.purposes
    if rejected is None:
        assert not isinstance(refused.value, OperationalEvidenceRejectedError)
        assert _refusals(store) == []
        return
    assert isinstance(refused.value, OperationalEvidenceRejectedError)
    (entry,) = _refusals(store)
    assert entry["purpose_id"] == "test-context-transition"
    assert entry["rejection_class"] == "stale"
    assert entry["rejection_ref"] == verifier.digest
    assert [item["entry"]["action_kind"] for item in store.audit_entries] == [
        "test_context.transition_refused"
    ]


async def test_heimdall_scoring_exclusion_names_the_class_in_outcome_version_1_2() -> None:
    verifier = _ClassVerifier({"forecast-context": _R.PARTIAL})
    provider = ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        admission_provider=_NoAdmission(),
        clock=lambda: _episode().closure_due_at,
        evidence=_requester(verifier),
    )
    observation = await provider.observe(_episode())
    reference = "operational-evidence-rejection:" + verifier.digest
    assert verifier.purposes == ["forecast-context"]
    assert observation.scoring_exclusions == ("operational_evidence_partial",)
    assert reference in observation.evidence_refs
    assert _observation_mapping(observation)["schema_version"] == "1.2.0"  # type: ignore[index]
    outcome = close_forecast(_expectation(), observation, closed_at=T0 + timedelta(hours=2))
    assert outcome.schema_version == "1.2.0"
    assert outcome.label.value == "unscorable"
    assert reference in outcome.evidence_refs
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "forecast-outcome", outcome.model_dump(mode="json")
    )
    generic = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        admission_provider=_NoAdmission(),
        clock=lambda: _episode().closure_due_at,
        evidence=_requester(_ClassVerifier({})),
    ).observe(_episode())
    assert generic.scoring_exclusions == ("intervention_history_unavailable",)
    assert not any(
        ref.startswith("operational-evidence-rejection:") for ref in generic.evidence_refs
    )
    legacy = close_forecast(_expectation(), generic, closed_at=T0 + timedelta(hours=2))
    assert legacy.schema_version == "1.1.0"


class _Collector:
    async def collect(self, request: object) -> dict[str, object]:
        return {kind: _record() for kind in _SLICES}


async def test_heimdall_retention_rejection_reaches_the_scoring_exclusion() -> None:
    verifier = _ClassVerifier({"forecast-history-actions": _R.CONFLICTING})
    retention = StateStoreForecastContextProvider(
        InMemoryStateStore(),
        admission=_NoAdmission(),
        collector=_Collector(),  # type: ignore[arg-type]
        evidence=_requester(verifier),
    )
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=retention,
        admission_provider=_NoAdmission(),
        clock=lambda: _episode().closure_due_at,
        evidence=_requester(_ClassVerifier({})),
    ).observe(_episode())
    assert verifier.purposes == ["forecast-history-actions"]
    assert observation.scoring_exclusions == ("operational_evidence_conflicting",)
    assert "operational-evidence-rejection:" + verifier.digest in observation.evidence_refs
    ingress = StateStoreForecastContextProvider(
        InMemoryStateStore(), admission=_NoAdmission(), evidence=_requester(verifier)
    )
    with pytest.raises(OperationalEvidenceRejectedError, match="operational_evidence_conflicting"):
        await ingress.ingest(
            {
                "producer_principal": "Huginn",
                "event_type": "forecast.context_history.v1",
                "attributes": {kind: _record() for kind in _SLICES},
            }
        )


@pytest.mark.parametrize("rejected", [_R.CROSS_SCOPE, None])
async def test_t1_reason_codes_name_the_class_and_cite_the_rejection(
    rejected: OperationalEvidenceRejectionClass | None,
) -> None:
    attempt = (
        _attempt(rejected)
        if rejected
        else OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.UNAVAILABLE)
    )
    tier, event = await _tier(_ReuseVerifier(decision_evidence=None, evidence_attempt=attempt))
    decision = await tier.evaluate(event=event)
    assert decision.outcome is T1Outcome.ABSTAIN
    if rejected is None:
        assert decision.reasons == ("decision_evidence_admission_missing",)
        return
    assert decision.reasons == (
        "operational_evidence_cross_scope",
        "operational-evidence-rejection:" + str(attempt.rejection_digest),
    )


async def test_current_reuse_feed_requests_issuance_and_keeps_the_attempt() -> None:
    verifier = _ClassVerifier({"current-case-reuse": _R.STALE})
    result = await AzureCurrentReuseVerifier(
        snapshots=_Snapshots(),
        safety=_Safety(),
        clock=_clock,
        admission_provider=_NoAdmission(),
        evidence=_requester(verifier),
    ).verify(event=_event(), action=_action(), context=_context())
    assert result.decision_evidence is None
    assert result.evidence_attempt.rejection_class is _R.STALE
    assert result.evidence_attempt.rejection_digest == verifier.digest
    (request,) = verifier.requests
    assert set(request.locator.coordinates) == {"case_ref", "resource_ref", "event_id"}


@pytest.mark.parametrize("rejected", [_R.CROSS_SCOPE, None])
async def test_pattern_read_status_names_the_class_and_reads_no_state(
    rejected: OperationalEvidenceRejectionClass | None,
) -> None:
    verifier = _ClassVerifier({"case-history-read": rejected} if rejected else {})
    never_read = AsyncMock()
    reader = OperatingPatternQuery(
        store=never_read,
        materializer=lambda: None,
        admission=_NoAdmission(),
        source_revision="example-release",
        clock=lambda: NOW,
        evidence=_requester(verifier),
    )
    invocation = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="operator-one",
        principal_scope_digest="sha256:" + "f" * 64,
        authentication_receipt_ref="sha256:" + "e" * 64,
        authentication_request_ref="semantic-request-test",
        purposes=("operations-review",),
    )
    arguments = {
        "access_scope_digest": "a" * 64,
        "purpose": "operational-learning",
        "failure_fingerprint": None,
        "limit": 5,
    }
    with pytest.raises(PermissionError, match="pattern query scope authorization failed") as held:
        await reader.read(arguments, invocation)
    never_read.read_state.assert_not_awaited()
    assert verifier.purposes == ["case-history-read"]
    if rejected is None:
        assert not isinstance(held.value, OperationalEvidenceRejectedError)
        return
    assert isinstance(held.value, OperationalEvidenceRejectedError)
    assert "operational_evidence_cross_scope" in str(held.value)
    assert verifier.digest in str(held.value)


def test_hold_reasons_keep_the_generic_reason_only_without_a_record() -> None:
    unavailable = OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.UNAVAILABLE)
    assert unavailable.hold_reasons("generic") == ("generic",)
    assert unavailable.rejection_ref is None
    rejected = _attempt(_R.SYNTHETIC_LIVE)
    assert rejected.hold_reasons("generic") == (
        "operational_evidence_synthetic_live",
        "operational-evidence-rejection:" + str(rejected.rejection_digest),
    )
    assert replace(rejected, rejection=None).hold_reason("generic") == "generic"


@pytest.mark.parametrize("rejected", [_R.REPLAY_SUBSTITUTED, None])
async def test_forseti_hold_cites_the_rejection_it_names(
    rejected: OperationalEvidenceRejectionClass | None,
) -> None:
    claim = _reviewed_claim()

    class _Source:
        async def read(self, **_kwargs: Any) -> Any:
            return claim

    class _ObservationOnly:
        async def admit(self, **values: str) -> DecisionEvidenceAdmission | None:
            if values["purpose_id"] == "operational-test-context":
                return None
            return DecisionEvidenceAdmission(
                receipt_digest="sha256:" + "b" * 64,
                verification_bundle_digest="sha256:" + "c" * 64,
                verified_at=NOW,
                valid_until=claim.effective_to,
                **values,
            )

    verifier = _ClassVerifier({"operational-test-context": rejected} if rejected else {})
    forseti = Forseti(
        test_context_source=_Source(),
        test_context_admission=_ObservationOnly(),
        test_context_clock=lambda: NOW,
    )
    forseti.bind_test_context_evidence(_requester(verifier))
    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "correlation_id": "test-context-example",
            "resource_id": claim.target_ref,
            "access_scope_digest": claim.access_scope_digest,
            "detected_at": NOW.isoformat(),
            "metric": claim.signal_code,
            "observed_value": 80.0,
            "service_impact": "none",
            "protected_signal": False,
        }
    )
    assert verdict is not None and verdict["resolved_autonomy_ceiling"] == "shadow_only"
    held = verdict["test_context"]
    if rejected is None:
        assert held["reason"] == "context_admission_required"
        assert held["evidence_rejection_ref"] is None
        return
    assert held["reason"] == "operational_evidence_replay_substituted"
    assert held["evidence_rejection_ref"] == verifier.digest
