"""Persisted G comparisons retain bounded digest-only evidence, never copied content."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.case_history import CaseHistoryRetentionService
from fdai.core.case_history.derived import CaseHistoryDerivedRetention, CaseHistoryProjectionStore
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    contextual_reuse_reasons,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    FINAL_QUALIFICATION_PURPOSE,
    BoundRetainedPatternAction,
    BoundRetainedPatternRequest,
    RetainedPatternQualification,
    RetainedReuseStatistics,
    qualification_request,
)
from fdai.core.tiers.t1_lightweight.retained_patterns import (
    RetainedPatternComparison,
    RetainedPatternSource,
)
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
    T1CandidateEligibility,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreDecisionEvidenceAdmissionRecorder,
    decision_evidence_state_key,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.decision_evidence_verification import DecisionEvidenceVerificationBundle
from fdai_service_contracts.ontology_query import content_digest

from tests.core.case_history.test_operational_case import T0
from tests.persistence.test_state_store_decision_evidence import (
    _bundle,
    _receipt,
    _requirement,
)
from tests.persistence.test_state_store_decision_evidence import (
    _Verifier as _ProofFixture,
)

from .test_contextual_reuse import _event
from .test_contextual_reuse import _Verifier as _ObservationFixture
from .test_eligibility_audit import _audit
from .test_retained_patterns import NOW, _retained


async def _retain_protocol_fixture_admission(
    store: InMemoryStateStore,
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
) -> None:
    """Exercise real gate/recorder/provider contracts, NOT live source qualification."""
    receipt = _receipt(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=purpose_id,
        source_revision=source_revision,
        event_at=T0,
        evidence_cutoff=T0 + timedelta(seconds=1),
        recorded_at=T0 + timedelta(seconds=2),
        fresh_until=T0 + timedelta(seconds=541),
    )
    original = _bundle(receipt)
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id=original.verifier_id,
        verifier_version=original.verifier_version,
        trust_anchor_id=original.trust_anchor_id,
        verified_at=T0 + timedelta(seconds=2),
        valid_until=T0 + timedelta(minutes=4),
        proofs=tuple(
            proof.model_copy(
                update={
                    "issued_at": T0 + timedelta(seconds=2),
                    "valid_until": T0 + timedelta(minutes=4),
                }
            )
            for proof in original.proofs
        ),
    )
    gate = DecisionEvidenceReadinessGate(
        registry=DecisionEvidenceVerifierRegistry(
            (
                DecisionEvidenceVerifierBinding(
                    authority_class=receipt.authority_class,
                    method_id=receipt.method_id,
                    verifier_id=bundle.verifier_id,
                    verifier_version=bundle.verifier_version,
                    trust_anchor_id=bundle.trust_anchor_id,
                    verifier=_ProofFixture(bundle),
                ),
            )
        )
    )
    requirement = _requirement().model_copy(
        update={
            "scope_digest": scope_digest,
            "purpose_id": purpose_id,
            "source_revision": source_revision,
        }
    )
    result = await gate.evaluate(receipt, requirement, evaluated_at=NOW)
    assert result.eligible, result.rejection_details
    assert await StateStoreDecisionEvidenceAdmissionRecorder(store=store, clock=lambda: NOW).retain(
        receipt, result
    )


@pytest.mark.parametrize(
    "withdrawal",
    [
        "none",
        "measurement",
        "source",
        "admission",
        "policy",
        "deadline",
        "final_measurement",
        "final_source",
        "final_read_admission",
        "qualification_missing",
        "qualification_mismatch",
        "qualification_deadline",
        "ordinary_admission",
    ],
)
async def test_real_query_stored_admissions_and_retained_source_reach_persisted_shadow_audit(
    withdrawal: str,
) -> None:
    """Synthetic protocol observations prove wiring only, never operational readiness."""
    harness = await _retained()
    assert harness.statistics is not None
    context = harness.action.operational_case
    assert context is not None
    event = _event()
    request = harness.request
    read_lookup = {
        "evidence_digest": content_digest(
            {"arguments": request.arguments(), "principal": request.context.model_dump(mode="json")}
        ),
        "scope_digest": content_digest(
            {
                "principal_scope": request.context.principal_scope_digest,
                "case_scope": request.access_scope_digest,
                "purpose": request.purpose,
            }
        ),
        "purpose_id": "case-history-read",
        "source_revision": "a" * 40,
    }
    observation: CurrentReuseVerification = await _ObservationFixture(
        decision_evidence=None
    ).verify(event=event, action=harness.action, context=context)  # type: ignore[no-untyped-call]
    reuse_lookup = {
        "evidence_digest": current_reuse_evidence_digest(observation),
        "scope_digest": current_reuse_scope_digest(
            event=event, action=harness.action, context=context
        ),
        "purpose_id": "current-case-reuse",
        "source_revision": context.graph_digest,
    }
    await _retain_protocol_fixture_admission(harness.durable, **read_lookup)
    await _retain_protocol_fixture_admission(harness.durable, **reuse_lookup)
    provider = StateStoreDecisionEvidenceAdmissionProvider(store=harness.durable, clock=lambda: NOW)
    assert await provider.admit(**read_lookup) is not None
    assert await provider.admit(**reuse_lookup) is not None
    verification_calls = 0
    statistics_calls = 0
    policy_allowed = True

    class _StoredCurrentVerifier:
        async def verify(
            self, *, event: Event, action: LearnedAction, context: OperationalCaseContext
        ) -> CurrentReuseVerification:
            nonlocal verification_calls
            verification_calls += 1
            if verification_calls == 2 and withdrawal == "deadline":
                await asyncio.Event().wait()
            admission = await provider.admit(
                **{
                    **reuse_lookup,
                    "scope_digest": current_reuse_scope_digest(
                        event=event, action=action, context=context
                    ),
                }
            )
            if verification_calls == 2:
                if withdrawal == "final_measurement":
                    harness.statistics = None
                elif withdrawal == "final_read_admission":
                    assert await harness.durable.delete_state(
                        decision_evidence_state_key(**read_lookup)
                    )
                elif withdrawal == "final_source":
                    negative = await harness.metadata.latest(
                        harness.cases[-1].case_id, access_scope_digest=request.access_scope_digest
                    )
                    assert negative is not None and negative.storage_ref is not None
                    await harness.artifacts.delete(negative.storage_ref)
            if verification_calls == 1:
                if withdrawal == "measurement":
                    harness.statistics = None
                elif withdrawal == "source":
                    record = await harness.metadata.latest(
                        harness.cases[-1].case_id, access_scope_digest=request.access_scope_digest
                    )
                    assert record is not None and record.storage_ref is not None
                    await harness.artifacts.delete(record.storage_ref)
            return replace(observation, decision_evidence=admission, policy_allowed=policy_allowed)

    async def current_statistics(
        event: Event, match: SimilarityMatch, evidence_ref: str
    ) -> RetainedReuseStatistics | None:
        nonlocal statistics_calls, policy_allowed
        statistics_calls += 1
        if statistics_calls == 2:
            if withdrawal == "admission":
                assert await harness.durable.delete_state(
                    decision_evidence_state_key(**reuse_lookup)
                )
            elif withdrawal == "policy":
                policy_allowed = False
        return await harness.read_statistics(event, match, evidence_ref)

    query = OperatingPatternQuery(
        store=harness.durable,
        materializer=lambda: harness.materializer,
        admission=provider,
        source_revision="a" * 40,
        clock=lambda: NOW,
    )
    bound = BoundRetainedPatternAction(
        str(event.event_id),
        harness.action.signature,
        SimilarityMatch(harness.action, 0.98),
        harness.statistics.evidence_ref,
        current_statistics,
    )
    verifier = _StoredCurrentVerifier()

    def immediate(operation: Coroutine[Any, Any, Any]) -> Any:
        """A TEST-ONLY single-event-loop-turn fence; never permits I/O or interleaving."""
        iterator = operation.__await__()
        try:
            next(iterator)
        except StopIteration as done:
            return done.value
        finally:
            iterator.close()
        raise AssertionError("the coherent in-memory fixture MUST NOT yield")

    class _CoherentFixtureQualifier:
        async def qualify(
            self, expected: RetainedPatternQualification
        ) -> DecisionEvidenceAdmission | None:
            # Unlike production stores, these fixtures can read the entire tuple
            # without yielding. This is NOT a production issuer or live qualification.
            if withdrawal == "qualification_missing":
                return None
            if withdrawal == "ordinary_admission":
                ordinary = immediate(provider.admit(**reuse_lookup))
                return ordinary if isinstance(ordinary, DecisionEvidenceAdmission) else None
            if withdrawal == "qualification_deadline":
                await asyncio.Event().wait()
            assert context is not None

            def versions() -> str:
                return repr(
                    (
                        harness.durable._state,
                        harness.metadata._records,
                        harness.artifacts._records,
                        harness.statistics,
                        harness.registry,
                        policy_allowed,
                    )
                )

            before = versions()
            try:
                observed = immediate(
                    verifier.verify(event=event, action=bound.match.action, context=context)
                )
                measured = immediate(bound.read_statistics(event, bound.match))
                result = immediate(query.read(request.arguments(), request.context))
                projections = CaseHistoryProjectionStore(
                    store=harness.durable,
                    materializer=harness.materializer,
                    access_scope_digest=request.access_scope_digest,
                    clock=lambda: NOW,
                )
                records = immediate(projections.pattern_records())
            except PermissionError:
                return None
            if (
                measured is None
                or before != versions()
                or result["unavailable"]
                or not measured.matches(bound.match, now=NOW)
                or contextual_reuse_reasons(
                    event=event,
                    action=bound.match.action,
                    context=context,
                    verification=observed,
                    evaluated_at=NOW,
                )
            ):
                return None
            cohort = next(
                (value for value in records if value["pattern_id"] == bound.pattern_id), None
            )
            if cohort is None:
                return None
            actual = qualification_request(
                event=event,
                arguments=request.arguments(),
                principal=request.context.model_dump(mode="json"),
                read_source_revision=query._source_revision,
                cohort=cohort,
                match=bound.match,
                statistics=measured,
                verification=observed,
            )
            if actual != expected:
                return None
            return DecisionEvidenceAdmission(
                receipt_digest=content_digest({"fixture-fence": expected.evidence_digest}),
                verification_bundle_digest=content_digest(
                    {"single-turn-fixture": expected.evidence_digest}
                ),
                evidence_digest=(
                    "sha256:" + "0" * 64
                    if withdrawal == "qualification_mismatch"
                    else expected.evidence_digest
                ),
                scope_digest=expected.scope_digest,
                purpose_id=FINAL_QUALIFICATION_PURPOSE,
                source_revision=expected.evidence_digest,
                verified_at=NOW,
                valid_until=NOW + timedelta(seconds=1),
            )

    harness.source = RetainedPatternSource(
        query=query,
        request_source=BoundRetainedPatternRequest(str(event.event_id), request),
        action_resolver=bound.resolve,
        action_types=lambda: harness.registry,
        store=harness.durable,
        materializer=lambda: harness.materializer,
        statistics_source=bound.read_statistics,
        final_qualifier=_CoherentFixtureQualifier(),
        clock=lambda: NOW,
    )
    decision = await harness.tier(
        verifier=verifier,
        timeout=0.02 if withdrawal in ("deadline", "qualification_deadline") else 5,
    ).evaluate(event=event)
    comparison = decision.retained_pattern_comparison
    assert comparison is not None
    if withdrawal != "none":
        assert comparison.challenger_match is None
        assert not comparison.candidates
        assert comparison.stop_reason in (
            "retained_pattern_source_changed",
            "retained_pattern_evidence_changed",
            "t1_deadline_exceeded",
            "retained_pattern_qualification_rejected",
        )
        assert decision.reason == "no_neighbour_found" and decision.best_match is None
        persisted = (await _audit(decision))["t1_retained_pattern_comparison"]
        assert persisted["checked_count"] == 0 and persisted["candidates"] == []
        assert persisted["challenger"]["match_identity_digest"] is None
        if withdrawal in ("admission", "policy", "deadline"):
            assert verification_calls == 2
        if withdrawal.startswith("final_"):
            assert verification_calls == 3
            assert comparison.stop_reason == "retained_pattern_qualification_rejected"
        if withdrawal == "admission":
            assert await provider.admit(**reuse_lookup) is None
        return
    assert comparison.challenger_match == bound.match
    assert verification_calls == 3
    assert comparison.final_qualification is not None
    assert comparison.candidates[0].current_reuse_verification is not None
    assert comparison.candidates[0].current_reuse_verification.decision_evidence == (
        await provider.admit(**reuse_lookup)
    )
    assert harness.action.success_rate == 0.95 and harness.action.reuse_count == 20
    persisted = (await _audit(decision))["t1_retained_pattern_comparison"]
    assert persisted["candidates"][0]["outcome"] == "eligible"
    assert persisted["operationally_proven"] is False
    assert persisted["challenger"]["outcome"] == "eligible"
    assert persisted["qualification_tuple_digest"] == (
        comparison.final_qualification.evidence_digest
    )
    assert persisted["qualification_receipt_digest"] == (
        comparison.final_qualification.receipt_digest
    )
    assert await harness.durable.verify_chain() is True

    # Even still-valid stored admissions cannot make deleted source evidence reusable.
    record = await harness.metadata.latest(
        harness.cases[-1].case_id, access_scope_digest=request.access_scope_digest
    )
    assert record is not None and record.storage_ref is not None
    await harness.artifacts.delete(record.storage_ref)
    after = await harness.tier(verifier=_StoredCurrentVerifier()).evaluate(event=event)
    assert await provider.admit(**read_lookup) is not None
    assert after.retained_pattern_comparison is not None
    assert after.retained_pattern_comparison.challenger_match is None
    assert (await _audit(after))["t1_retained_pattern_comparison"]["checked_count"] == 0


async def test_audit_bounds_and_redacts_even_manually_constructed_comparison_inputs() -> None:
    harness = await _retained()
    decision = await harness.tier().evaluate(event=_event())
    comparison = decision.retained_pattern_comparison
    assert comparison is not None
    match = SimilarityMatch(harness.action, 0.98)
    injected = RetainedPatternComparison(
        candidates=(T1CandidateEligibility(match, True, ()),) * 10,
        challenger_match=match,
        pattern_ids=("private provider identity",) * 10,
        statistics_refs=("private evidence locator",) * 10,
        stop_reason="private provider error",
    )
    persisted = (await _audit(replace(decision, retained_pattern_comparison=injected)))[
        "t1_retained_pattern_comparison"
    ]
    assert persisted["checked_count"] == 10
    assert persisted["recorded_candidate_count"] == 5
    assert persisted["candidates_truncated"] is True
    assert len(persisted["pattern_ids"]) == len(persisted["statistics_refs"]) == 5
    assert persisted["stop_reason"]["code"] == "redacted"
    assert "private" not in json.dumps(persisted)
    assert persisted["execution_authority"] is persisted["promotion_authority"] is False
    assert persisted["operationally_proven"] is False
    assert persisted["challenger"]["outcome"] == "held"
    assert persisted["challenger"]["match_identity_digest"] is None
    assert all(value["outcome"] == "ineligible" for value in persisted["candidates"])


async def test_json_rehydrated_projection_is_read_without_new_index_or_copied_evidence() -> None:
    harness = await _retained()
    key = "case-history-derived:v1:" + "f" * 64
    retained = await harness.durable.read_state(key)
    assert retained is not None
    harness.durable = InMemoryStateStore()
    await harness.durable.write_state(key, json.loads(json.dumps(retained)))
    harness.restart()
    decision = await harness.tier().evaluate(event=_event())
    assert decision.retained_pattern_comparison is not None
    assert decision.retained_pattern_comparison.stop_reason == (
        "retained_pattern_qualification_unavailable"
    )
    assert await harness.durable.read_state(key) == retained
    assert (await _audit(decision))["t1_retained_pattern_comparison"]["checked_count"] == 0


async def test_existing_retention_purges_sources_and_no_g_copy_survives_restart() -> None:
    harness = await _retained()
    decision = await harness.tier().evaluate(event=_event())
    assert decision.retained_pattern_comparison is not None
    assert decision.retained_pattern_comparison.stop_reason == (
        "retained_pattern_qualification_unavailable"
    )
    record = await harness.metadata.latest(harness.cases[0].case_id, access_scope_digest="f" * 64)
    assert record is not None
    retention = CaseHistoryRetentionService(
        metadata=harness.metadata,
        artifacts=harness.artifacts,
        derived_data=CaseHistoryDerivedRetention(
            store=harness.durable, materializer=harness.materializer
        ),
    )
    removed = await retention.delete_due(now=record.deletion_due_at)
    assert set(removed) == {case.case_id for case in harness.cases}
    harness.restart()
    after = await harness.tier().evaluate(event=_event())
    assert after.retained_pattern_comparison is not None
    assert after.retained_pattern_comparison.challenger_match is None
    assert after.retained_pattern_comparison.stop_reason == "no_retained_pattern"
    assert harness.calls == 1
    row = await _audit(after)
    assert row["t1_retained_pattern_comparison"]["statistics_refs"] == []
