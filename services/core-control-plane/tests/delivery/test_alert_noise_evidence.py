"""No-network decoder fixtures, not evidence of real admission, Azure truth or authority.

Positive DE receipts/bundles are fabricated ONLY in these InMemoryStateStore unit fixtures.
Production readers use the real retained-admission provider; no production verifier is added.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.delivery.alert_noise_evidence import (
    ALERT_EVALUATION_PURPOSE,
    ALERT_SCOPE_EVIDENCE_PURPOSE,
    AdmittedAlertEvidenceSource,
    StateStoreAlertEvaluationReader,
    alert_evaluation_key,
    alert_evidence_binding_digest,
    alert_scope_digest,
    read_admitted_alert_record,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    StateStoreDecisionEvidenceAdmissionProvider,
    decision_evidence_record_mapping,
    decision_evidence_state_key,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.alert_noise import AlertDelivery, AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.persistence.test_state_store_decision_evidence import _receipt

SOURCE = "commit:" + "a" * 40
ANCHOR = "fixture:alert-ledger"
SCOPE = alert_scope_digest(tenant_ref="tenant:example", scope_ref="scope:example")
SCOPE_KEY = "alert-noise:scope-evidence:scope:example"


@pytest.fixture
def ledger(now: datetime) -> SimpleNamespace:
    clock = [now]
    store = InMemoryStateStore(linearization_clock=lambda: clock[0])
    admissions = StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: clock[0])
    return SimpleNamespace(store=store, admissions=admissions, clock=clock)


async def _install_record(ledger, *, key, payload, purpose, receipt_changes=None, anchor=ANCHOR):
    """Install clearly test-only positive wire shapes into an isolated in-memory ledger."""
    at = ledger.clock[0]
    values = dict(
        evidence_digest=content_digest(payload),
        scope_digest=SCOPE,
        purpose_id=purpose,
        source_revision=SOURCE,
        event_at=at,
        evidence_cutoff=at,
        recorded_at=at,
        fresh_until=at + timedelta(hours=2),
        freshness_ceiling_seconds=7200,
    )
    values.update(receipt_changes or {})
    receipt = _receipt(**values)
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=receipt.receipt_digest,
            subject_digest=subject,
            proof_digest=content_digest({"fixture": str(kind), "subject": subject}),
            verifier_id="alert-fixture-verifier",
            verifier_version="1.0.0",
            trust_anchor_id=anchor,
            issued_at=at,
            valid_until=at + timedelta(hours=2),
        )
        for kind, subject in subjects.items()
    )
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id="alert-fixture-verifier",
        verifier_version="1.0.0",
        trust_anchor_id=anchor,
        verified_at=at,
        valid_until=at + timedelta(hours=2),
        proofs=proofs,
    )
    admission = DecisionEvidenceAdmission(
        receipt_digest=receipt.receipt_digest,
        verification_bundle_digest=bundle.bundle_digest,
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
        verified_at=at,
        valid_until=at + timedelta(hours=2),
    )
    retained = RetainedDecisionEvidence(receipt, bundle, admission)
    await ledger.store.write_state(
        key, {"payload": payload, "receipt": receipt.model_dump(mode="json")}
    )
    await ledger.store.write_state(
        decision_evidence_state_key(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        ),
        decision_evidence_record_mapping(retained),
    )
    return receipt, admission


def _base_and_enrichment(evidence: AlertEvidence) -> tuple[AlertEvidence, AlertEvidence]:
    base = evidence.model_copy(
        update={
            "stamp": evidence.stamp.model_copy(
                update={
                    "source": "azure-monitor-read-v1",
                    "synthetic": False,
                    "coverage": "partial",
                    "reasons": ("ownership_unavailable",),
                    "valid_until": evidence.stamp.recorded_at + timedelta(minutes=10),
                }
            ),
            "rules": tuple(
                row.model_copy(
                    update={
                        "classification": "unknown",
                        "service_ref": "service:unknown",
                        "ownership_verified": False,
                        "iac_owned": False,
                        "active_incident": True,
                    }
                )
                for row in evidence.rules
            ),
            "groups": tuple(
                row.model_copy(update={"reverse_complete": False}) for row in evidence.groups
            ),
            "audiences": tuple(
                row.model_copy(
                    update={
                        "member_refs": (),
                        "potential_members": None,
                        "coverage": "unavailable",
                        "primary_verified": False,
                        "backup_verified": False,
                    }
                )
                for row in evidence.audiences
            ),
        }
    )
    enriched = evidence.model_copy(
        update={
            "stamp": base.stamp.model_copy(update={"coverage": "complete", "reasons": ()}),
            "audiences": tuple(
                row.model_copy(
                    update={"member_refs": tuple(f"principal:{n:064x}" for n in range(10))}
                )
                for row in evidence.audiences
            ),
        }
    )
    return base, _rebind(base, enriched)


def _rebind(base: AlertEvidence, enriched: AlertEvidence) -> AlertEvidence:
    digest = alert_evidence_binding_digest(base_digest=digest_record(base), evidence=enriched)
    return enriched.model_copy(
        update={"stamp": enriched.stamp.model_copy(update={"revision": digest})}
    )


def _source(ledger, base):
    inner = SimpleNamespace(collect=AsyncMock(return_value=base))
    source = AdmittedAlertEvidenceSource(
        inner=inner,
        store=ledger.store,
        admissions=ledger.admissions,
        scope_ref="scope:example",
        tenant_ref="tenant:example",
        source_revision=SOURCE,
        clock=lambda: ledger.clock[0],
    )
    return source, inner


async def _read(ledger, key="alert-noise:fixture", **changes):
    options = dict(
        store=ledger.store,
        admissions=ledger.admissions,
        key=key,
        purpose="alert-noise-fixture",
        scope_digest=SCOPE,
        source_revision=SOURCE,
        now=ledger.clock[0],
    )
    return await read_admitted_alert_record(**{**options, **changes})


async def test_absence_and_self_attested_receipt_never_admit(ledger):
    assert await _read(ledger) is None
    await _install_record(
        ledger, key="alert-noise:fixture", payload={"value": 1}, purpose="alert-noise-fixture"
    )
    assert await _read(ledger, admissions=None) is None
    isolated = InMemoryStateStore()
    await isolated.write_state(
        "alert-noise:fixture", await ledger.store.read_state("alert-noise:fixture")
    )
    assert (
        await _read(
            ledger,
            store=isolated,
            admissions=StateStoreDecisionEvidenceAdmissionProvider(
                store=isolated, clock=lambda: ledger.clock[0]
            ),
        )
        is None
    )


async def test_exact_independent_record_is_detached_and_has_no_public_source_identity(ledger):
    await _install_record(
        ledger, key="alert-noise:fixture", payload={"nested": [1]}, purpose="alert-noise-fixture"
    )
    record = await _read(ledger)
    assert record is not None and record.admission.execution_authority is False
    record.payload["nested"].append(2)
    assert record.payload == {"nested": [1]}
    assert "inventory-reader" not in repr(record)
    ledger.clock[0] += timedelta(hours=2)
    with pytest.raises(AlertExecutionHeld):
        record.require_current(now=ledger.clock[0])


@pytest.mark.parametrize(
    "changes",
    [
        {"synthetic": True},
        {"completeness_basis_points": 9999},
        {"conflict_status": "unknown"},
        {"evidence_digest": "sha256:" + "f" * 64},
        {"scope_digest": "sha256:" + "f" * 64},
        {"purpose_id": "other-purpose"},
        {"source_revision": "commit:" + "f" * 40},
    ],
)
async def test_complete_exact_receipt_fields_are_required(ledger, changes):
    await _install_record(
        ledger,
        key="alert-noise:fixture",
        payload={"value": 1},
        purpose="alert-noise-fixture",
        receipt_changes=changes,
    )
    with pytest.raises(AlertExecutionHeld):
        await _read(ledger)


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", 0),
        ("execution_authority", 0),
        ("execution_authority", True),
        ("receipt_digest", "sha256:" + "f" * 64),
    ],
)
async def test_receipt_booleans_and_digest_are_not_coerced(ledger, field, value):
    await _install_record(
        ledger, key="alert-noise:fixture", payload={"value": 1}, purpose="alert-noise-fixture"
    )
    raw = await ledger.store.read_state("alert-noise:fixture")
    raw["receipt"][field] = value
    await ledger.store.write_state("alert-noise:fixture", raw)
    with pytest.raises(AlertExecutionHeld):
        await _read(ledger)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"payload": {}, "receipt": {}, "extra": False},
        {"payload": {1: "not-a-json-key"}, "receipt": {}},
        {"payload": {"bytes": "x" * 2_000_001}, "receipt": {}},
        {"payload": {"value": float("nan")}, "receipt": {}},
    ],
)
async def test_untrusted_json_is_closed_and_bounded(ledger, raw):
    # A provider double intentionally supplies impossible database JSON for boundary checks.
    store = SimpleNamespace(read_state=AsyncMock(return_value=raw))
    with pytest.raises(AlertExecutionHeld):
        await _read(ledger, store=store)


async def test_replacement_during_independent_admission_is_rejected(ledger):
    await _install_record(
        ledger, key="alert-noise:fixture", payload={"nested": [1]}, purpose="alert-noise-fixture"
    )
    admit = ledger.admissions.admit

    async def replacing(**kwargs):
        result = await admit(**kwargs)
        raw = await ledger.store.read_state("alert-noise:fixture")
        raw["payload"]["nested"].append(2)
        await ledger.store.write_state("alert-noise:fixture", raw)
        return result

    with pytest.raises(AlertExecutionHeld, match="changed"):
        await _read(ledger, admissions=SimpleNamespace(admit=replacing))


async def test_another_admission_receipt_cannot_vouch_for_this_record(ledger):
    _, admitted = await _install_record(
        ledger, key="alert-noise:fixture", payload={"value": 1}, purpose="alert-noise-fixture"
    )
    provider = SimpleNamespace(
        admit=AsyncMock(return_value=replace(admitted, receipt_digest="sha256:" + "f" * 64))
    )
    with pytest.raises(AlertExecutionHeld, match="admission"):
        await _read(ledger, admissions=provider)


async def test_native_read_precedes_optional_supplement_and_absence_preserves_partial(
    ledger, evidence
):
    base, _ = _base_and_enrichment(evidence)
    source, inner = _source(ledger, base)
    read_state = ledger.store.read_state

    async def ordered(key):
        inner.collect.assert_awaited_once_with(now=ledger.clock[0])
        return await read_state(key)

    ledger.store.read_state = ordered
    assert await source.collect(now=ledger.clock[0]) == base


async def test_admitted_enrichment_preserves_native_provenance_and_has_no_authority(
    ledger, evidence
):
    base, enriched = _base_and_enrichment(evidence)
    await _install_record(
        ledger,
        key=SCOPE_KEY,
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
        payload={"base_digest": digest_record(base), "evidence": enriched.model_dump(mode="json")},
    )
    source, inner = _source(ledger, base)
    result = await source.collect(now=ledger.clock[0])
    assert result == enriched and result.execution_authority is False
    inner.collect.assert_awaited_once()


async def test_private_native_reader_failure_is_not_replaced_or_echoed(ledger, evidence):
    base, _ = _base_and_enrichment(evidence)
    source, inner = _source(ledger, base)
    inner.collect.side_effect = RuntimeError("private provider detail")
    with pytest.raises(AlertExecutionHeld, match="alert_evidence_unavailable") as failure:
        await source.collect(now=ledger.clock[0])
    assert "private provider detail" not in str(failure.value)


async def test_partial_base_cannot_expose_unpseudonymized_members_without_a_supplement(
    ledger, evidence
):
    base, _ = _base_and_enrichment(evidence)
    base = base.model_copy(
        update={
            "audiences": (
                base.audiences[0].model_copy(update={"member_refs": ("person:unredacted",)}),
                base.audiences[1],
            )
        }
    )
    with pytest.raises(AlertExecutionHeld, match="native_evidence_invalid"):
        await _source(ledger, base)[0].collect(now=ledger.clock[0])


@pytest.mark.parametrize(
    "change",
    [
        {"severity": 0},
        {"kind": "log"},
        {"group_refs": ("group:new",)},
        {"enabled": False},
        {"stateful": False},
        {"resource_ref": "resource:other"},
        {"revision": "sha256:" + "f" * 64},
    ],
)
async def test_even_admitted_supplement_cannot_rewrite_native_configuration(
    ledger, evidence, change
):
    base, enriched = _base_and_enrichment(evidence)
    enriched = _rebind(
        base, enriched.model_copy(update={"rules": (enriched.rules[0].model_copy(update=change),)})
    )
    await _install_record(
        ledger,
        key=SCOPE_KEY,
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
        payload={"base_digest": digest_record(base), "evidence": enriched.model_dump(mode="json")},
    )
    with pytest.raises(AlertExecutionHeld):
        await _source(ledger, base)[0].collect(now=ledger.clock[0])


@pytest.mark.parametrize(
    "what",
    [
        "base",
        "window",
        "revision",
        "principal",
        "protected",
        "source",
        "groups",
        "coverage",
        "chronology",
    ],
)
async def test_enrichment_requires_exact_scope_window_identity_and_known_classification(
    ledger, evidence, what
):
    base, enriched = _base_and_enrichment(evidence)
    if what == "window":
        enriched = enriched.model_copy(
            update={"window_start": enriched.window_start + timedelta(seconds=1)}
        )
    if what == "principal":
        members = ("principal:not-pseudonymized", *enriched.audiences[0].member_refs[1:])
        enriched = enriched.model_copy(
            update={
                "audiences": (
                    enriched.audiences[0].model_copy(update={"member_refs": members}),
                    enriched.audiences[1],
                )
            }
        )
    if what == "protected":
        base = base.model_copy(
            update={"rules": (base.rules[0].model_copy(update={"classification": "security"}),)}
        )
    if what == "source":
        enriched = enriched.model_copy(
            update={"stamp": enriched.stamp.model_copy(update={"source": "other:reader"})}
        )
    if what == "groups":
        enriched = enriched.model_copy(update={"groups": enriched.groups[:1]})
    if what == "coverage":
        enriched = enriched.model_copy(update={"history_coverage": "partial"})
    if what == "chronology":
        enriched = enriched.model_copy(
            update={
                "stamp": enriched.stamp.model_copy(
                    update={"recorded_at": ledger.clock[0] + timedelta(minutes=1)}
                )
            }
        )
    enriched = _rebind(base, enriched)
    if what == "revision":
        enriched = enriched.model_copy(
            update={"stamp": enriched.stamp.model_copy(update={"revision": "sha256:" + "f" * 64})}
        )
    await _install_record(
        ledger,
        key=SCOPE_KEY,
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
        payload={
            "base_digest": "sha256:" + "f" * 64 if what == "base" else digest_record(base),
            "evidence": enriched.model_dump(mode="json"),
        },
    )
    if what == "chronology":
        ledger.clock[0] += timedelta(minutes=2)
    with pytest.raises(AlertExecutionHeld):
        await _source(ledger, base)[0].collect(now=ledger.clock[0])


async def test_native_history_cannot_be_relabelled_by_supplement(ledger, evidence):
    base, enriched = _base_and_enrichment(evidence)
    event = AlertDelivery(
        ref="event:example",
        episode_ref="episode:example",
        rule_ref="rule:example",
        condition="fired",
        state="source",
        event_at=base.window_start,
        receipt_ref="receipt:original",
    )
    base = base.model_copy(update={"deliveries": (event,)})
    enriched = _rebind(
        base,
        enriched.model_copy(
            update={
                "deliveries": (
                    event.model_copy(update={"rule_revision": evidence.rules[0].revision}),
                )
            }
        ),
    )
    await _install_record(
        ledger,
        key=SCOPE_KEY,
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
        payload={"base_digest": digest_record(base), "evidence": enriched.model_dump(mode="json")},
    )
    with pytest.raises(AlertExecutionHeld, match="history_changed"):
        await _source(ledger, base)[0].collect(now=ledger.clock[0])


def _comparison(evidence, now):
    baseline = evidence.rules[0].evaluation
    treatment = AlertTreatment(
        kind="evaluation",
        target_ref=evidence.rules[0].ref,
        evaluation=baseline.model_copy(update={"threshold": 85.0}),
    )
    comparison = EvaluationReceipt(
        rule_ref=treatment.target_ref,
        rule_revision=evidence.rules[0].revision,
        scenario_digest="sha256:" + "e" * 64,
        baseline=baseline,
        treatment=treatment.evaluation,
        evaluated_at=now,
        expires_at=now + timedelta(hours=1),
        baseline_true_positive=1,
        treatment_true_positive=1,
        baseline_false_positive=1,
        treatment_false_positive=0,
        baseline_false_negative=0,
        treatment_false_negative=0,
        accepted=True,
        reason="improved_without_recall_loss",
    )
    return treatment, comparison


@pytest.mark.parametrize(
    "change", [None, "rule", "baseline", "treatment", "stale", "post-verification"]
)
async def test_comparison_is_exact_current_and_independently_admitted(ledger, evidence, change):
    _, enriched = _base_and_enrichment(evidence)
    treatment, comparison = _comparison(enriched, ledger.clock[0])
    reader = StateStoreAlertEvaluationReader(
        store=ledger.store,
        admissions=ledger.admissions,
        scope_ref="scope:example",
        tenant_ref="tenant:example",
        source_revision=SOURCE,
        clock=lambda: ledger.clock[0],
    )
    assert await reader.read(evidence=enriched, treatment=treatment, now=ledger.clock[0]) is None
    if change == "rule":
        comparison = comparison.model_copy(update={"rule_revision": "sha256:" + "f" * 64})
    if change in {"baseline", "treatment"}:
        value = getattr(comparison, change).model_copy(update={"threshold": 81.0})
        comparison = comparison.model_copy(update={change: value})
    if change == "stale":
        comparison = comparison.model_copy(
            update={
                "evaluated_at": ledger.clock[0] - timedelta(hours=1),
                "expires_at": ledger.clock[0],
            }
        )
    if change == "post-verification":
        comparison = comparison.model_copy(
            update={"evaluated_at": ledger.clock[0] + timedelta(minutes=1)}
        )
    await _install_record(
        ledger,
        key=alert_evaluation_key(evidence=enriched, treatment=treatment),
        purpose=ALERT_EVALUATION_PURPOSE,
        payload={
            "evidence_digest": digest_record(enriched),
            "treatment_digest": digest_record(treatment),
            "comparison": comparison.model_dump(mode="json"),
        },
    )
    if change == "post-verification":
        ledger.clock[0] += timedelta(minutes=2)
    if change is None:
        assert (
            await reader.read(evidence=enriched, treatment=treatment, now=ledger.clock[0])
            == comparison
        )
        other = treatment.model_copy(
            update={"evaluation": treatment.evaluation.model_copy(update={"threshold": 90.0})}
        )
        assert await reader.read(evidence=enriched, treatment=other, now=ledger.clock[0]) is None
    else:
        with pytest.raises(AlertExecutionHeld):
            await reader.read(evidence=enriched, treatment=treatment, now=ledger.clock[0])
