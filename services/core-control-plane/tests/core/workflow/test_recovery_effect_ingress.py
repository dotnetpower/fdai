"""Production ingress coverage for independent recovery effect observations.

An effect is only verified when an authority independent of the executor and
the provider reports it. These tests drive the exact versioned event a
production observer publishes and prove the ingress refuses executor-authored,
synthetic, stale, unfinal, uncontained, and malformed evidence, binds an
accepted observation to one persisted recovery attempt, and stays safe under
duplicate and reordered delivery.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_effect_ingress import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
    RecoveryEffectObservationIngress,
    RecoveryEffectObservationRejection,
    RecoveryEffectObservationWrite,
)
from fdai.delivery.persistence.workflow_recovery import (
    StateStoreRecoveryAttemptResolver,
    StateStoreRecoveryEffectObservationJournal,
    StateStoreRecoveryEffectObserver,
    recovery_effect_observation_key,
)
from fdai.delivery.workflow_recovery_observation_handler import (
    RecoveryEffectObservationHandler,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_TARGET = "resource:example/rg/recovery-ingress-1"
_PROCESS_ID = "process-recovery-ingress-1"
_SOURCE_REVISION = "commit:" + "a" * 40
_EXECUTOR = "executor@example.com"
_OBSERVER = "heimdall-observer@example.com"
_PROVIDER = "provider@example.com"
_FAILED_PROPOSAL = "sha256:" + "b" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_ACTION_TYPE = "workflow.recovery.reconcile"
_PARAMS: dict[str, object] = {"reason": "reconcile the partially applied change"}
_OBSERVER_PRINCIPAL = "Heimdall"


def _target_digest(target_ref: str = _TARGET) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


def _attempt() -> RecoveryAttemptIdentity:
    return RecoveryAttemptIdentity.create(
        process_id=_PROCESS_ID,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        hold_revision=1,
        recovery_action_type=_ACTION_TYPE,
        recovery_payload_digest=content_digest(
            {
                "action_type": _ACTION_TYPE,
                "params": dict(_PARAMS),
                "purpose": "workflow-recovery-payload",
            }
        ),
        target_digest=_target_digest(),
        source_revision=_SOURCE_REVISION,
        attempt_number=1,
    )


async def _persist_attempt(store: InMemoryStateStore, attempt: RecoveryAttemptIdentity) -> None:
    """Write the attempt record the coordinator persists before dispatch."""

    key = f"workflow:recovery-attempt:{attempt.identity_digest.removeprefix('sha256:')}"
    await store.write_state(
        key,
        {
            "process_id": attempt.process_id,
            "recovery_step_id": recovery_attempt_step_id(attempt),
            "attempt_identity_digest": attempt.identity_digest,
            "failed_compensation_proposal_digest": (attempt.failed_compensation_proposal_digest),
            "hold_revision": attempt.hold_revision,
            "recovery_action_type": attempt.recovery_action_type,
            "recovery_payload_digest": attempt.recovery_payload_digest,
            "target_digest": attempt.target_digest,
            "source_revision": attempt.source_revision,
            "attempt_number": attempt.attempt_number,
            "execution_authority": False,
            "revision": 1,
        },
    )


def _event(
    attempt: RecoveryAttemptIdentity,
    **overrides: Any,
) -> dict[str, Any]:
    """Return the exact versioned payload an independent observer publishes."""

    payload: dict[str, Any] = {
        "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
        "observation_schema_version": RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
        "producer_principal": _OBSERVER_PRINCIPAL,
        "process_id": _PROCESS_ID,
        "recovery_step_id": recovery_attempt_step_id(attempt),
        "attempt_identity_digest": attempt.identity_digest,
        "target_resource_id": _TARGET,
        "provider_receipt_digest": _RECEIPT_DIGEST,
        "observer_identity": _OBSERVER,
        "observer_authority_class": "authoritative_external",
        "provider_identity": _PROVIDER,
        "purpose_version": "1.0.0",
        "method_version": "1.0.0",
        "event_time": (_NOW - timedelta(minutes=3)).isoformat(),
        "recorded_time": (_NOW - timedelta(minutes=2)).isoformat(),
        "freshness_policy_seconds": 600,
        "completeness": True,
        "provenance": "azure-resource-graph",
        "conflict_status": "none",
        "synthetic": False,
        "evidence_digest": "sha256:" + "7" * 64,
        "expected_effect_digest": "sha256:" + "8" * 64,
        "approved_envelope_digest": "sha256:" + "9" * 64,
        "action_digest": "sha256:" + "3" * 64,
        "evidence_window_start": (_NOW - timedelta(minutes=4)).isoformat(),
        "evidence_window_end": (_NOW - timedelta(minutes=1)).isoformat(),
        "watermarks": [
            {
                "source_id": "azure-activity-log",
                "watermark": (_NOW - timedelta(minutes=1)).isoformat(),
                "final": True,
                "watermark_digest": "sha256:" + "4" * 64,
            }
        ],
        "forbidden_effect_observed": False,
        "envelope_contained": True,
        "success": True,
    }
    payload.update(overrides)
    return payload


def _ingress(
    store: InMemoryStateStore,
    *,
    bind_journal: bool = True,
) -> RecoveryEffectObservationIngress:
    return RecoveryEffectObservationIngress(
        attempts=StateStoreRecoveryAttemptResolver(store),
        journal=(
            StateStoreRecoveryEffectObservationJournal(
                store=store,
                executor_identity=_EXECUTOR,
            )
            if bind_journal
            else None
        ),
        executor_identity=_EXECUTOR,
        authorized_principals=frozenset({_OBSERVER_PRINCIPAL}),
        trusted_observer_identities=frozenset({_OBSERVER}),
        clock=lambda: _NOW,
    )


async def _bound() -> tuple[InMemoryStateStore, RecoveryAttemptIdentity]:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    attempt = _attempt()
    await StateStoreAutomationHoldLedger(store, clock=lambda: _NOW).issue(
        target_ref=_TARGET,
        process_id=_PROCESS_ID,
        reason="compensation_failed",
    )
    await _persist_attempt(store, attempt)
    return store, attempt


class TestIndependentObservationIsAccepted:
    async def test_an_authoritative_event_becomes_readable_evidence(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(
            _event(attempt),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.accepted is True
        assert result.write is RecoveryEffectObservationWrite.RECORDED
        assert result.attempt_identity_digest == attempt.identity_digest
        assert result.effect_verification_authority is False
        assert result.execution_authority is False
        stored = await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
        assert stored is not None
        assert stored["observer_identity"] == _OBSERVER
        assert stored["effect_verification_authority"] is False
        observed = await StateStoreRecoveryEffectObserver(store).observe_recovery_effect(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observed_at=_NOW,
        )
        assert observed is not None
        assert observed.success is True
        assert observed.finalized is True

    async def test_the_observer_path_handler_relays_the_same_event(self) -> None:
        store, attempt = await _bound()
        handler = RecoveryEffectObservationHandler(ingress=_ingress(store))

        accepted = await handler.handle(_event(attempt), _OBSERVER_PRINCIPAL)

        assert accepted is True
        assert (
            await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
            is not None
        )

    async def test_the_handler_refuses_an_executor_authored_relay(self) -> None:
        store, attempt = await _bound()
        handler = RecoveryEffectObservationHandler(ingress=_ingress(store))

        accepted = await handler.handle(
            _event(attempt, producer_principal="Thor"),
            "Thor",
        )

        assert accepted is False
        assert (
            await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
            is None
        )


class TestDuplicateAndReorderedDelivery:
    async def test_an_exact_replay_is_a_duplicate_not_a_second_record(self) -> None:
        store, attempt = await _bound()
        ingress = _ingress(store)

        first = await ingress.observe(
            _event(attempt),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )
        second = await ingress.observe(
            _event(attempt),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert first.write is RecoveryEffectObservationWrite.RECORDED
        assert second.accepted is True
        assert second.duplicate is True
        writes = [
            row
            for row in store.audit_entries
            if row["entry"].get("action_kind") == "workflow.recovery.effect_observed"
        ]
        assert len(writes) == 1

    async def test_a_reordered_event_never_overwrites_the_first_authority(self) -> None:
        store, attempt = await _bound()
        ingress = _ingress(store)
        await ingress.observe(_event(attempt), authenticated_principal=_OBSERVER_PRINCIPAL)

        stale = await ingress.observe(
            _event(
                attempt,
                success=False,
                evidence_digest="sha256:" + "6" * 64,
                event_time=(_NOW - timedelta(minutes=5)).isoformat(),
                recorded_time=(_NOW - timedelta(minutes=5)).isoformat(),
            ),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert stale.accepted is False
        assert stale.rejection is RecoveryEffectObservationRejection.CONFLICTING_OBSERVATION
        stored = await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
        assert stored is not None
        assert stored["success"] is True
        assert stored["evidence_digest"] == "sha256:" + "7" * 64


class TestDependentOrUnusableEvidenceIsRefused:
    @pytest.mark.parametrize(
        ("overrides", "rejection"),
        [
            (
                {"observer_identity": _EXECUTOR},
                RecoveryEffectObservationRejection.OBSERVER_NOT_INDEPENDENT,
            ),
            (
                {"observer_identity": _PROVIDER},
                RecoveryEffectObservationRejection.OBSERVER_NOT_INDEPENDENT,
            ),
            (
                {"observer_authority_class": "executor_controlled"},
                RecoveryEffectObservationRejection.AUTHORITY_CLASS_INELIGIBLE,
            ),
            (
                {"observer_authority_class": "provider_dispatch"},
                RecoveryEffectObservationRejection.AUTHORITY_CLASS_INELIGIBLE,
            ),
            (
                {"synthetic": True},
                RecoveryEffectObservationRejection.SYNTHETIC_EVIDENCE,
            ),
            (
                {"forbidden_effect_observed": True},
                RecoveryEffectObservationRejection.CONTAINMENT_UNPROVEN,
            ),
            (
                {"envelope_contained": False},
                RecoveryEffectObservationRejection.CONTAINMENT_UNPROVEN,
            ),
            (
                {"completeness": False},
                RecoveryEffectObservationRejection.FINALITY_INCOMPLETE,
            ),
            (
                {"conflict_status": "conflicting"},
                RecoveryEffectObservationRejection.FINALITY_INCOMPLETE,
            ),
            (
                {
                    "watermarks": [
                        {
                            "source_id": "azure-activity-log",
                            "watermark": (_NOW - timedelta(minutes=1)).isoformat(),
                            "final": False,
                            "watermark_digest": "sha256:" + "4" * 64,
                        }
                    ]
                },
                RecoveryEffectObservationRejection.FINALITY_INCOMPLETE,
            ),
            (
                {"watermarks": []},
                RecoveryEffectObservationRejection.FINALITY_INCOMPLETE,
            ),
            (
                {
                    "evidence_window_start": (_NOW - timedelta(hours=3)).isoformat(),
                    "evidence_window_end": (_NOW - timedelta(hours=2)).isoformat(),
                },
                RecoveryEffectObservationRejection.EVIDENCE_STALE,
            ),
            (
                {"evidence_window_end": (_NOW + timedelta(minutes=5)).isoformat()},
                RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID,
            ),
            (
                {
                    "evidence_window_start": (_NOW - timedelta(minutes=1)).isoformat(),
                    "evidence_window_end": (_NOW - timedelta(minutes=4)).isoformat(),
                },
                RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID,
            ),
            (
                {"recorded_time": (_NOW - timedelta(minutes=9)).isoformat()},
                RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID,
            ),
            (
                {"observation_schema_version": "2.0.0"},
                RecoveryEffectObservationRejection.SCHEMA_VERSION_UNSUPPORTED,
            ),
            (
                {"event_type": "workflow.recovery.effect_observed"},
                RecoveryEffectObservationRejection.EVENT_TYPE_UNSUPPORTED,
            ),
            (
                {"evidence_digest": "not-a-digest"},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"provider_receipt_digest": "sha256:zz"},
                RecoveryEffectObservationRejection.PROVIDER_RECEIPT_INVALID,
            ),
            (
                {"event_time": "2026-09-11T11:57:00"},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"purpose_version": ""},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"success": "true"},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"watermarks": "azure-activity-log"},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"target_resource_id": "resource:example/rg/other"},
                RecoveryEffectObservationRejection.TARGET_MISMATCH,
            ),
            (
                {"attempt_identity_digest": "sha256:" + "5" * 64},
                RecoveryEffectObservationRejection.ATTEMPT_MISMATCH,
            ),
            (
                {"recovery_step_id": "compensate_apply"},
                RecoveryEffectObservationRejection.MALFORMED_PAYLOAD,
            ),
            (
                {"recovery_step_id": f"recover_{'f' * 32}"},
                RecoveryEffectObservationRejection.ATTEMPT_UNKNOWN,
            ),
            (
                {"process_id": "process-other"},
                RecoveryEffectObservationRejection.ATTEMPT_UNKNOWN,
            ),
        ],
    )
    async def test_the_named_rejection_is_reported_and_nothing_is_stored(
        self,
        overrides: Mapping[str, Any],
        rejection: RecoveryEffectObservationRejection,
    ) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(
            _event(attempt, **overrides),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.accepted is False
        assert result.rejection is rejection
        assert (
            await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
            is None
        )


class TestObserverAuthentication:
    async def test_an_unauthenticated_relay_is_refused(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(_event(attempt), authenticated_principal="  ")

        assert result.rejection is RecoveryEffectObservationRejection.OBSERVER_UNAUTHENTICATED

    async def test_an_unauthorized_principal_is_refused(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(
            _event(attempt, producer_principal="Vidar"),
            authenticated_principal="Vidar",
        )

        assert result.rejection is RecoveryEffectObservationRejection.OBSERVER_NOT_AUTHORIZED

    async def test_a_payload_may_not_claim_another_principal(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(
            _event(attempt, producer_principal="Thor"),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.rejection is RecoveryEffectObservationRejection.OBSERVER_UNAUTHENTICATED

    async def test_an_untrusted_observer_identity_is_refused(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store).observe(
            _event(attempt, observer_identity="attacker-declared-observer"),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.rejection is RecoveryEffectObservationRejection.OBSERVER_IDENTITY_UNTRUSTED

    async def test_an_executor_relay_is_never_independent(self) -> None:
        store, attempt = await _bound()
        ingress = RecoveryEffectObservationIngress(
            attempts=StateStoreRecoveryAttemptResolver(store),
            journal=StateStoreRecoveryEffectObservationJournal(
                store=store,
                executor_identity=_OBSERVER_PRINCIPAL,
            ),
            executor_identity=_OBSERVER_PRINCIPAL,
            authorized_principals=frozenset({_OBSERVER_PRINCIPAL}),
            trusted_observer_identities=frozenset({_OBSERVER}),
            clock=lambda: _NOW,
        )

        result = await ingress.observe(
            _event(attempt),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.rejection is RecoveryEffectObservationRejection.OBSERVER_NOT_INDEPENDENT


class TestUnboundIntakeStaysNamed:
    async def test_an_unbound_journal_names_the_missing_binding(self) -> None:
        store, attempt = await _bound()

        result = await _ingress(store, bind_journal=False).observe(
            _event(attempt),
            authenticated_principal=_OBSERVER_PRINCIPAL,
        )

        assert result.accepted is False
        assert result.rejection is RecoveryEffectObservationRejection.INTAKE_UNBOUND
        assert (
            await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
            is None
        )
