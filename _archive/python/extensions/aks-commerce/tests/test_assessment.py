from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
)

from fdai_aks_commerce import (
    AksCommerceAssessmentPolicy,
    AksCommerceEvidenceFrame,
    assess_aks_commerce,
)
from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_issuance import (
    AcceptanceReceiptIssuer,
    AcceptanceTrustLifecycle,
)
from fdai_aks_commerce.acceptance_receipts import (
    REVOCATION_PREFIX,
    AcceptanceTrustBinding,
    StoredOrderAcceptanceReceiptVerifier,
    acceptance_receipt_payload,
)
from fdai_aks_commerce.acceptance_store import (
    StoredOrderAcceptanceSource,
    decode_acceptance_evidence,
    retain_order_acceptance,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _metric(name: str, current: float, previous: float = 0) -> AksCommerceMetric:
    return AksCommerceMetric(
        name=name,
        unit="count",
        current=current,
        previous=previous,
        source_ref="source:example",
        observed_at=NOW,
        state=AksCommerceEvidenceState.COMPLETE,
    )


def _frame(
    *,
    metrics: tuple[AksCommerceMetric, ...],
    breached: bool = False,
    gaps: tuple[str, ...] = (),
    deployment_changed: bool = False,
    rollout_stalled: bool = False,
    prior_degraded: bool = False,
) -> AksCommerceEvidenceFrame:
    return AksCommerceEvidenceFrame(
        service_id="order-fulfillment",
        observed_at=NOW,
        window_start=NOW - timedelta(minutes=5),
        window_end=NOW,
        dependency_path=("storefront", "order-api", "order-queue", "order-processor"),
        workloads=(
            AksCommerceWorkload(
                workload_id="order-processor",
                display_name="Order processor",
                resource_ref="resource:processor",
                ready=True,
                revision="revision-1",
                evidence_state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        slos=(
            AksCommerceSlo(
                slo_id="order-fulfillment.availability",
                objective_ratio=0.99,
                observed_ratio=0.95 if breached else 1,
                budget_remaining_ratio=0 if breached else 1,
                breached=breached,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        ),
        metrics=metrics,
        evidence_refs=("evidence:example",),
        evidence_gaps=gaps,
        deployment_changed=deployment_changed,
        rollout_stalled=rollout_stalled,
        prior_degraded=prior_degraded,
    )


def _required_metrics(
    *,
    active: tuple[float, float] = (0, 0),
    incoming: float = 10,
    completed: float = 10,
    dead_letters: tuple[float, float] = (0, 0),
) -> tuple[AksCommerceMetric, ...]:
    return (
        _metric("synthetic.order.availability", 1, 1),
        _metric("stream.active_messages", active[0], active[1]),
        _metric("stream.incoming_messages", incoming),
        _metric("stream.completed_messages", completed),
        _metric("stream.dead_letter_messages", dead_letters[0], dead_letters[1]),
    )


def test_growing_queue_is_order_backlog() -> None:
    projection = assess_aks_commerce(
        _frame(metrics=_required_metrics(active=(25, 5), incoming=30, completed=10))
    )

    assert projection.status is AksCommerceStatus.ORDER_BACKLOG
    assert projection.complete is True


def test_rollout_failure_with_backlog_is_deployment_regression() -> None:
    projection = assess_aks_commerce(
        _frame(
            metrics=_required_metrics(active=(25, 5), incoming=30, completed=10),
            breached=True,
            deployment_changed=True,
            rollout_stalled=True,
        )
    )

    assert projection.status is AksCommerceStatus.DEPLOYMENT_REGRESSION


def test_dead_letter_growth_has_priority_over_backlog() -> None:
    projection = assess_aks_commerce(
        _frame(
            metrics=_required_metrics(
                active=(25, 5),
                incoming=30,
                completed=10,
                dead_letters=(2, 0),
            )
        )
    )

    assert projection.status is AksCommerceStatus.DEAD_LETTER_GROWTH


def test_missing_required_metric_holds_instead_of_guessing() -> None:
    projection = assess_aks_commerce(
        _frame(metrics=(_metric("synthetic.order.availability", 1, 1),))
    )

    assert projection.status is AksCommerceStatus.HELD
    assert projection.complete is False
    assert "metric_missing.stream.active_messages" in projection.evidence_gaps


def test_prior_degradation_closes_only_on_complete_healthy_evidence() -> None:
    projection = assess_aks_commerce(_frame(metrics=_required_metrics(), prior_degraded=True))

    assert projection.status is AksCommerceStatus.RECOVERED


@pytest.mark.parametrize("prior_degraded", [False, True])
@pytest.mark.parametrize(
    ("availability", "ready", "breached"),
    [
        (0, False, True),
        (0, True, False),
        (1, False, False),
        (1, True, True),
    ],
)
def test_unproven_health_with_idle_queue_never_closes_incident(
    availability: float,
    ready: bool,
    breached: bool,
    prior_degraded: bool,
) -> None:
    frame = _frame(
        metrics=_required_metrics(incoming=0, completed=0), prior_degraded=prior_degraded
    )
    frame = replace(
        frame,
        metrics=(frame.metrics[0].model_copy(update={"current": availability}), *frame.metrics[1:]),
        workloads=(frame.workloads[0].model_copy(update={"ready": ready}),),
        slos=(frame.slos[0].model_copy(update={"breached": breached}),),
    )

    projection = assess_aks_commerce(frame)

    assert projection.status is AksCommerceStatus.HELD
    assert projection.complete is False
    assert projection.evidence_gaps == ("health_not_proven",)
    assert projection.proposed_action is None


def test_complete_healthy_evidence_remains_healthy() -> None:
    projection = assess_aks_commerce(_frame(metrics=_required_metrics()))

    assert projection.status is AksCommerceStatus.HEALTHY
    assert projection.complete is True
    assert projection.evidence_gaps == ()


def test_dependency_pressure_and_deployment_regression_without_backlog() -> None:
    base = _frame(metrics=_required_metrics(), breached=True)
    pressure_frame = replace(base, order_store_pressure=True)
    assert assess_aks_commerce(pressure_frame).status is AksCommerceStatus.DEPENDENCY_PRESSURE

    regression_frame = replace(base, deployment_changed=True, rollout_stalled=True)
    assert assess_aks_commerce(regression_frame).status is AksCommerceStatus.DEPLOYMENT_REGRESSION


def test_evidence_frame_and_policy_validation_guards() -> None:
    base = _frame(metrics=_required_metrics())
    with pytest.raises(ValueError, match="service_id is unsupported"):
        replace(base, service_id="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(base, observed_at=datetime(2026, 9, 17))
    with pytest.raises(ValueError, match="window is invalid"):
        replace(base, window_start=NOW, window_end=NOW)
    with pytest.raises(ValueError, match="1 to 16 workloads"):
        replace(base, dependency_path=())
    with pytest.raises(ValueError, match="must not contain cycles"):
        replace(base, dependency_path=("a", "a"))
    with pytest.raises(ValueError, match="workloads must contain 1 to 16"):
        replace(base, workloads=())
    with pytest.raises(ValueError, match="SLO evidence must contain 1 to 8"):
        replace(base, slos=())
    with pytest.raises(ValueError, match="exceeds its bounds"):
        replace(base, evidence_refs=tuple(f"ref:{i}" for i in range(65)))
    with pytest.raises(ValueError, match="evidence refs must be unique"):
        replace(base, evidence_refs=("dup", "dup"))
    with pytest.raises(ValueError, match="evidence gaps must be bounded and unique"):
        replace(base, evidence_gaps=("dup", "dup"))

    dup_metrics = (*base.metrics, _metric("synthetic.order.availability", 1, 1))
    dup_frame = replace(base, metrics=dup_metrics)
    with pytest.raises(ValueError, match="is duplicated"):
        dup_frame.metric("synthetic.order.availability")

    incomplete_frame = replace(
        base,
        workloads=(
            base.workloads[0].model_copy(
                update={"evidence_state": AksCommerceEvidenceState.UNAVAILABLE}
            ),
        ),
        slos=(base.slos[0].model_copy(update={"state": AksCommerceEvidenceState.UNAVAILABLE}),),
        metrics=(
            base.metrics[0].model_copy(update={"state": AksCommerceEvidenceState.UNAVAILABLE}),
            *base.metrics[1:],
        ),
    )
    assert incomplete_frame.derived_gaps == (
        "workload_evidence_incomplete",
        "slo_evidence_incomplete",
        "metric_evidence_incomplete",
    )

    with pytest.raises(ValueError, match="growth thresholds must be positive"):
        AksCommerceAssessmentPolicy(backlog_growth_minimum=0)


def _acc_intent() -> OrderAcceptanceIntent:
    return OrderAcceptanceIntent(
        policy_ref="policy:example",
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )


def _acc_evidence() -> OrderAcceptanceEvidence:
    intent = _acc_intent()
    return OrderAcceptanceEvidence(
        resource_ref=intent.resource_ref,
        service_resource_ref=intent.service_resource_ref,
        cluster_ref=intent.cluster_ref,
        namespace=intent.namespace,
        deployment_name=intent.deployment_name,
        deployment_uid=intent.deployment_uid,
        resource_version="1",
        observed_at=NOW,
        desired_replicas=0,
        ready_replicas=0,
        ready_endpoints=0,
        probes=tuple(
            OrderAcceptanceProbe(
                evidence_ref=f"probe:{i}",
                observed_at=NOW - timedelta(seconds=2 - i),
                accepted=False,
                authorization_ref="auth:probe",
            )
            for i in range(2)
        ),
        kubernetes_evidence_ref="obs:k8s",
        verification_ref="sha256:" + "a" * 64,
        complete=True,
        sample=False,
        maintenance_active=False,
        hpa_managed=False,
        competing_writer=False,
    )


async def test_acceptance_issuance_receipts_and_store_validation_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = _acc_intent()
    evidence = _acc_evidence()
    key = Ed25519PrivateKey.generate()
    pub = key.public_key()

    with pytest.raises(ValueError, match="issuer key id is invalid"):
        AcceptanceReceiptIssuer(
            private_key=key,
            key_id="BAD_KEY",
            issuer_identity="issuer:1",
            source_identity="source:1",
            executor_identity="exec:1",
            intent=intent,
        )
    with pytest.raises(ValueError, match="identities must be exact"):
        AcceptanceReceiptIssuer(
            private_key=key,
            key_id="key-1",
            issuer_identity=" ",
            source_identity="source:1",
            executor_identity="exec:1",
            intent=intent,
        )
    issuer = AcceptanceReceiptIssuer(
        private_key=key,
        key_id="key-1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        intent=intent,
        clock=lambda: NOW,
    )
    assert issuer.executor_identity == "exec:1"

    naive_issuer = AcceptanceReceiptIssuer(
        private_key=key,
        key_id="key-1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        intent=intent,
        clock=lambda: datetime(2026, 9, 17),
    )
    with pytest.raises(ValueError, match="clock must be timezone-aware"):
        naive_issuer.issue(evidence)

    closed_intent = replace(intent)
    object.__setattr__(closed_intent, "max_age_seconds", 0)
    closed_issuer = AcceptanceReceiptIssuer(
        private_key=key,
        key_id="key-1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        intent=closed_intent,
        clock=lambda: NOW,
    )
    real_eval = evaluate_order_acceptance
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_issuance.evaluate_order_acceptance",
        lambda *_a, **_kw: SimpleNamespace(
            status="unavailable", evidence_digest="sha256:" + "a" * 64
        ),
    )
    with pytest.raises(ValueError, match="validity window is closed"):
        closed_issuer.issue(evidence)
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_issuance.evaluate_order_acceptance",
        real_eval,
    )

    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="trust key id is invalid"):
        AcceptanceTrustLifecycle(
            store=store,
            key_id="BAD",
            trust_owner_identity="owner:1",
            issuer_identity="issuer:1",
            source_identity="source:1",
            executor_identity="exec:1",
        )
    with pytest.raises(ValueError, match="trust identities must be exact"):
        AcceptanceTrustLifecycle(
            store=store,
            key_id="key-1",
            trust_owner_identity="",
            issuer_identity="issuer:1",
            source_identity="source:1",
            executor_identity="exec:1",
        )
    with pytest.raises(ValueError, match="must be distinct"):
        AcceptanceTrustLifecycle(
            store=store,
            key_id="key-1",
            trust_owner_identity="dup",
            issuer_identity="dup",
            source_identity="source:1",
            executor_identity="exec:1",
        )
    naive_lifecycle = AcceptanceTrustLifecycle(
        store=store,
        key_id="key-1",
        trust_owner_identity="owner:1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        clock=lambda: datetime(2026, 9, 17),
    )
    with pytest.raises(ValueError, match="trust clock must be timezone-aware"):
        await naive_lifecycle.activate(valid_until=NOW + timedelta(seconds=10))

    lifecycle = AcceptanceTrustLifecycle(
        store=store,
        key_id="key-1",
        trust_owner_identity="owner:1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="must end in the future"):
        await lifecycle.activate(valid_until=NOW)
    await lifecycle.activate(valid_until=NOW + timedelta(seconds=30))
    await lifecycle.activate(valid_until=NOW + timedelta(seconds=30))
    with pytest.raises(ValueError, match="different activation"):
        await lifecycle.activate(valid_until=NOW + timedelta(seconds=40))
    with pytest.raises(ValueError, match="reason code is invalid"):
        await lifecycle.revoke(reason_code="BAD_REASON")
    await lifecycle.revoke(reason_code="reason_one")
    with pytest.raises(ValueError, match="another revocation"):
        await lifecycle.revoke(reason_code="reason_two")

    class _RacedRevokeStore(InMemoryStateStore):
        def __init__(self, retained: dict[str, Any] | None) -> None:
            super().__init__()
            self.reads = 0
            self.retained = retained

        async def read_state(self, key: str) -> dict[str, Any] | None:
            self.reads += 1
            return None if self.reads == 1 else self.retained

        async def write_state_with_audit_if_absent(
            self, key: str, value: dict[str, Any], audit_metadata: dict[str, Any]
        ) -> bool:
            return False

    raced_ok = AcceptanceTrustLifecycle(
        store=_RacedRevokeStore(
            {"key_id": "key-1", "reason_code": "reason_one", "revoked_at": NOW.isoformat()}
        ),
        key_id="key-1",
        trust_owner_identity="owner:1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        clock=lambda: NOW,
    )
    await raced_ok.revoke(reason_code="reason_one")

    raced_conflict = AcceptanceTrustLifecycle(
        store=_RacedRevokeStore({"key_id": "key-1", "reason_code": "other"}),
        key_id="key-1",
        trust_owner_identity="owner:1",
        issuer_identity="issuer:1",
        source_identity="source:1",
        executor_identity="exec:1",
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="another revocation"):
        await raced_conflict.revoke(reason_code="reason_one")

    with pytest.raises(ValueError, match="fields do not match"):
        acceptance_receipt_payload({"bad": 1})
    with pytest.raises(ValueError, match="bounded deployment trust"):
        StoredOrderAcceptanceReceiptVerifier(
            store=store, intent=intent, trust={}, executor_identity="exec:1"
        )
    with pytest.raises(ValueError, match="verifier key id is invalid"):
        StoredOrderAcceptanceReceiptVerifier(
            store=store,
            intent=intent,
            trust={"BAD": AcceptanceTrustBinding("issuer:1", "source:1", pub)},
            executor_identity="exec:1",
        )
    with pytest.raises(ValueError, match="identities must be bounded"):
        StoredOrderAcceptanceReceiptVerifier(
            store=store,
            intent=intent,
            trust={"key-1": AcceptanceTrustBinding("", "source:1", pub)},
            executor_identity="exec:1",
        )
    with pytest.raises(ValueError, match="must be distinct"):
        StoredOrderAcceptanceReceiptVerifier(
            store=store,
            intent=intent,
            trust={"key-1": AcceptanceTrustBinding("dup", "dup", pub)},
            executor_identity="exec:1",
        )

    clean_store = InMemoryStateStore()
    verifier = StoredOrderAcceptanceReceiptVerifier(
        store=clean_store,
        intent=intent,
        trust={"key-1": AcceptanceTrustBinding("issuer:1", "source:1", pub)},
        executor_identity="exec:1",
        clock=lambda: NOW,
    )
    issued = issuer.issue(evidence)
    vref = issued.evidence.verification_ref
    edigest = str(issued.receipt["evidence_digest"])
    assert await verifier.verify(verification_ref="invalid", evidence_digest=edigest) is False
    assert await verifier.verify(verification_ref=vref, evidence_digest=edigest) is False
    assert (
        await verifier.verify_record(
            {**issued.receipt, "key_id": "other"},
            verification_ref=vref,
            evidence_digest=edigest,
        )
        is False
    )
    assert (
        await verifier.verify_record(
            {**issued.receipt, "signature": "not-hex"},
            verification_ref=vref,
            evidence_digest=edigest,
        )
        is False
    )
    assert (
        await verifier.verify_record(issued.receipt, verification_ref=vref, evidence_digest=edigest)
        is False
    )
    await clean_store.write_state(
        REVOCATION_PREFIX + "key-1",
        {"key_id": "key-1", "revoked": False, "valid_until": 123},
    )
    assert (
        await verifier.verify_record(issued.receipt, verification_ref=vref, evidence_digest=edigest)
        is False
    )

    with pytest.raises(ValueError, match="probe authorization references"):
        await retain_order_acceptance(
            store=clean_store,
            verifier=verifier,
            intent=intent,
            evidence=issued.evidence,
            receipt={**issued.receipt, "authorization_refs": ["other"]},
            now=NOW,
        )
    with pytest.raises(ValueError, match="receipt is not authenticated"):
        await retain_order_acceptance(
            store=clean_store,
            verifier=verifier,
            intent=intent,
            evidence=issued.evidence,
            receipt=issued.receipt,
            now=NOW,
        )

    await clean_store.write_state(
        REVOCATION_PREFIX + "key-1",
        {
            "key_id": "key-1",
            "revoked": False,
            "valid_until": (NOW + timedelta(seconds=30)).isoformat(),
        },
    )
    await clean_store.write_state("aks-commerce:acceptance-receipt:v1:" + vref, {"conflict": 1})
    with pytest.raises(ValueError, match="conflicts with retained evidence"):
        await retain_order_acceptance(
            store=clean_store,
            verifier=verifier,
            intent=intent,
            evidence=issued.evidence,
            receipt=issued.receipt,
            now=NOW,
        )

    with pytest.raises(ValueError, match="observation fields are invalid"):
        decode_acceptance_evidence("not-a-dict")
    with pytest.raises(ValueError, match="probe records are invalid"):
        decode_acceptance_evidence(
            {**{f: None for f in issued.evidence.__dataclass_fields__}, "probes": ["bad"]}
        )

    for bad_record, match in (
        ({"bad": 1}, "fields are invalid"),
        (
            {"policy_ref": "other", "evidence_digest": edigest, "evidence": {}},
            "policy does not match",
        ),
        (
            {
                "policy_ref": intent.policy_ref,
                "evidence_digest": "sha256:" + "0" * 64,
                "evidence": {
                    **{
                        k: getattr(issued.evidence, k) for k in issued.evidence.__dataclass_fields__
                    },
                    "observed_at": NOW.isoformat(),
                    "probes": [
                        {
                            "evidence_ref": p.evidence_ref,
                            "observed_at": p.observed_at.isoformat(),
                            "accepted": p.accepted,
                            "authorization_ref": p.authorization_ref,
                            "synthetic_traffic": p.synthetic_traffic,
                        }
                        for p in issued.evidence.probes
                    ],
                },
            },
            "digest does not match",
        ),
    ):
        obs_store = InMemoryStateStore()
        await obs_store.write_state(
            "aks-commerce:acceptance-observation:v1:" + (await _obs_prefix(intent)) + "item",
            bad_record,
        )
        with pytest.raises(ValueError, match=match):
            await StoredOrderAcceptanceSource(obs_store).observe(intent)


async def _obs_prefix(intent: OrderAcceptanceIntent) -> str:
    from fdai_aks_commerce.acceptance_store import _prefix

    return _prefix(intent).removeprefix("aks-commerce:acceptance-observation:v1:")
