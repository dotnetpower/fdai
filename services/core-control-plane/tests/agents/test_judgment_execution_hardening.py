"""Judgment and execution hardening regressions (Forseti, Thor, action semantics)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_judgment import JudgmentTable
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.thor import ActionRunState, Thor
from fdai.core.architecture_review import ArchitectureReviewObservation
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _semantics(*, reversible: bool = True) -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"test.auto": not reversible},
        rollback_by_id={"test.auto": "state_forward_only"},
    )


def _table() -> JudgmentTable:
    return JudgmentTable(
        rule_match={"test.event": "test.auto"},
        risk_verdict={"test.auto": "auto"},
        source="test-judgment-table",
    )


def test_forseti_uses_digest_stamped_table_and_lowers_auto_without_catalog() -> None:
    f = Forseti(judgment_table=_table())

    verdict = asyncio.run(
        f.judge({"event_type": "test.event", "resource_id": "r", "correlation_id": "c"})
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["judgment_table_digest"] == _table().digest
    assert verdict["quorum_required"] == 2
    assert verdict["idempotency_key"].startswith("forseti-verdict:")


def test_forseti_allows_auto_only_for_bound_known_reversible_action() -> None:
    f = Forseti(judgment_table=_table(), action_semantics=_semantics(reversible=True))

    verdict = asyncio.run(
        f.judge({"event_type": "test.event", "resource_id": "r", "correlation_id": "c"})
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "auto"
    assert verdict["quorum_required"] == 1


def test_revoked_rule_state_caps_auto_to_hil() -> None:
    f = Forseti(judgment_table=_table(), action_semantics=_semantics(reversible=True))
    asyncio.run(
        f.on_typed_message(
            "object.rule",
            {"producer_principal": "Mimir", "action_type": "test.auto", "state": "revoked"},
        )
    )

    verdict = asyncio.run(
        f.judge({"event_type": "test.event", "resource_id": "r", "correlation_id": "c"})
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert f.health()["rule_state_cached"] == 1


def test_no_rule_match_repeats_are_folded_with_health_counter() -> None:
    bus = _bus()
    f = Forseti(bus=bus)
    event = {"event_type": "unknown", "resource_id": "r", "correlation_id": "fold-c"}

    first = asyncio.run(f.judge(dict(event)))
    second = asyncio.run(f.judge(dict(event)))

    assert first is not None
    assert second is None
    assert len(bus.messages_on("object.verdict")) == 1
    assert next(iter(f.health()["no_rule_folds"].values())) == 2


def test_forseti_records_unbound_architecture_review_in_health() -> None:
    f = Forseti()

    asyncio.run(f.on_typed_message("object.change", {"correlation_id": "change-1"}))

    assert f.health()["architecture_review_bound"] is False
    assert f.behavior_snapshot()["architecture_review:unbound"] == 1


def test_forseti_rejects_specialist_advice_from_wrong_owner() -> None:
    bus = _bus()
    f = Forseti(bus=bus)

    asyncio.run(
        f.on_typed_message(
            "object.cost-anomaly",
            {
                "producer_principal": "Freyr",
                "correlation_id": "bad-advice",
                "resource_id": "r",
                "recommendation": "scale_down",
            },
        )
    )

    assert f.behavior_snapshot()["specialist_advice:rejected_owner"] == 1
    assert bus.messages_on("object.arbitration-request") == []


def test_security_and_arbitration_publications_have_stable_keys() -> None:
    bus = _bus()
    f = Forseti(bus=bus, rbac={"guest@example.com": frozenset()})

    asyncio.run(
        f.judge(
            {
                "event_type": "test.event",
                "action_type": "test.auto",
                "resource_id": "r",
                "correlation_id": "sec-c",
                "initiator_principal": "guest@example.com",
                "operator_initiated": True,
            }
        )
    )
    asyncio.run(
        f.maybe_request_arbitration(
            {
                "correlation_id": "arb-c",
                "resource_id": "r",
                "domain_advice": {"cost": "scale_down", "capacity": "scale_up"},
            }
        )
    )

    assert (
        bus.messages_on("object.security-event")[0]
        .payload["idempotency_key"]
        .startswith("forseti-security-event:")
    )
    assert (
        bus.messages_on("object.arbitration-request")[0]
        .payload["idempotency_key"]
        .startswith("forseti-arbitration-request:")
    )


def test_thor_lowers_auto_quorum_two_and_rejects_keyless_verdict_visibly() -> None:
    bus = _bus()
    thor = Thor(bus=bus)

    keyless = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "keyless",
                "producer_principal": "Forseti",
                "action_type": "test.auto",
                "risk_verdict": "auto",
                "resource_id": "r-keyless",
            }
        )
    )
    hil = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "quorum-c",
                "idempotency_key": "quorum-key",
                "action_type": "test.auto",
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
                "resource_id": "r-quorum",
                "quorum_required": 2,
            }
        )
    )

    assert keyless.state is ActionRunState.DENY_DROPPED
    assert keyless.outcome == "missing_verdict_idempotency_key"
    assert hil.state is ActionRunState.HIL_PENDING
    assert thor.behavior_snapshot()["dispatch:auto_quorum_lowered"] == 1


def test_thor_resource_contention_becomes_visible_terminal_action_run() -> None:
    bus = _bus()
    thor = Thor(bus=bus)
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "held-c",
                "idempotency_key": "held-key",
                "action_type": "test.auto",
                "risk_verdict": "hil",
                "resource_id": "shared-r",
            }
        )
    )

    rejected = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "contender-c",
                "idempotency_key": "contender-key",
                "action_type": "test.auto",
                "risk_verdict": "auto",
                "resource_id": "shared-r",
            }
        )
    )

    assert rejected.state is ActionRunState.DENY_DROPPED
    assert rejected.outcome == "resource_active_action_run_contention"
    assert any(
        msg.payload["correlation_id"] == "contender-c" and msg.payload["state"] == "deny_dropped"
        for msg in bus.messages_on("object.action-run")
    )


def test_thor_correlation_reuse_becomes_visible_rejection_without_replacing_run() -> None:
    thor = Thor()
    held = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "reuse-c",
                "idempotency_key": "generation-1",
                "action_type": "test.auto",
                "risk_verdict": "hil",
                "resource_id": "r1",
            }
        )
    )

    rejected = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "reuse-c",
                "idempotency_key": "generation-2",
                "action_type": "test.auto",
                "risk_verdict": "hil",
                "resource_id": "r2",
            }
        )
    )

    assert thor.action_runs["reuse-c"] is held
    assert rejected.state is ActionRunState.DENY_DROPPED
    assert rejected.outcome == "correlation_reuse_rejected"


def test_thor_terminal_timestamp_uses_injected_clock() -> None:
    fixed = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    bus = _bus()
    thor = Thor(bus=bus, clock=lambda: fixed)

    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "clock-c",
                "idempotency_key": "clock-key",
                "action_type": "test.auto",
                "risk_verdict": "deny",
                "resource_id": "r-clock",
            }
        )
    )

    terminal = bus.messages_on("object.action-run")[-1].payload
    assert terminal["state"] == "deny_dropped"
    assert terminal["terminal_at"] == "2030-01-02T03:04:05Z"


def test_forseti_defers_owner_scoped_observations_and_rejects_bad_incident_owner() -> None:
    f = Forseti()

    with pytest.raises(ValueError, match="Huginn-owned"):
        asyncio.run(
            f.on_typed_message(
                "object.event",
                {
                    "event_type": INCIDENT_INTERVENTION_EVENT_TYPE,
                    "producer_principal": "Bragi",
                },
            )
        )
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "event_type": INCIDENT_INTERVENTION_EVENT_TYPE,
                "producer_principal": "Huginn",
            },
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {"event_type": "control_plane.t2_proposer_failure"},
        )
    )
    asyncio.run(f.on_typed_message("object.event", {"event_type": "specialist.cost.sample"}))
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {"event_type": "detection.readiness.observed"},
        )
    )

    behavior = f.behavior_snapshot()
    assert behavior["incident_guidance:deferred"] == 1
    assert behavior["t2_proposer_observation:deferred"] == 1
    assert behavior["specialist_signal:deferred"] == 1
    assert behavior["detection_readiness:observation_deferred"] == 1


def test_forseti_rule_state_rejects_bad_owner_and_invalid_payload() -> None:
    f = Forseti()

    asyncio.run(
        f.on_typed_message(
            "object.rule",
            {"producer_principal": "Saga", "action_type": "test.auto", "state": "revoked"},
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.rule",
            {"producer_principal": "Mimir", "action_type": "", "state": "revoked"},
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.rule",
            {"producer_principal": "Mimir", "action_type": "test.auto", "state": "promoted"},
        )
    )

    assert f.behavior_snapshot()["rule_state:rejected_owner"] == 1
    assert f.behavior_snapshot()["rule_state:invalid"] == 1
    assert f.health()["rule_state_cached"] == 1


def test_forseti_architecture_review_failure_duplicate_and_publish_paths() -> None:
    class _FailingLoop:
        async def evaluate(self, payload: dict[str, object]) -> ArchitectureReviewObservation:
            raise RuntimeError("review unavailable")

    class _ReplayedLoop:
        async def evaluate(self, payload: dict[str, object]) -> ArchitectureReviewObservation:
            observation = ArchitectureReviewObservation.hold(
                change_id="change-1",
                idempotency_key="idem-1",
                correlation_id="corr-1",
                target_ref="target-1",
                change_digest="digest-1",
                reason="duplicate",
            )
            object.__setattr__(observation, "replayed", True)
            return observation

    bus = _bus()
    failing = Forseti(bus=bus, architecture_review_loop=_FailingLoop())  # type: ignore[arg-type]
    asyncio.run(failing.on_typed_message("object.change", {"id": "change-1"}))
    assert failing.behavior_snapshot()["architecture_review:failed"] == 1
    assert bus.messages_on("object.verdict")

    replayed = Forseti(architecture_review_loop=_ReplayedLoop())  # type: ignore[arg-type]
    asyncio.run(replayed.on_typed_message("object.change", {"id": "change-1"}))
    assert replayed.behavior_snapshot()["architecture_review:duplicate"] == 1


def test_thor_rejects_invalid_constructor_values_and_naive_clock() -> None:
    with pytest.raises(ValueError, match="hil_timeout_seconds"):
        Thor(hil_timeout_seconds=0)
    with pytest.raises(ValueError, match="executor_timeout_seconds"):
        Thor(executor_timeout_seconds=0)

    thor = Thor(clock=lambda: datetime(2030, 1, 1))
    with pytest.raises(RuntimeError, match="timezone-aware"):
        thor._now()  # noqa: SLF001 - focused clock safety branch


def test_thor_rejects_double_test_context_guard_binding_and_binds_store_clock() -> None:
    thor = Thor(clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    guard = object()
    thor.bind_test_context_dispatch_guard(guard)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="already bound"):
        thor.bind_test_context_dispatch_guard(guard)  # type: ignore[arg-type]

    from fdai.agents._framework.provider_adapters import StateStoreActionRunStore

    store = StateStoreActionRunStore(InMemoryStateStore())
    thor.set_state_store(store)
    assert store._now() == datetime(2030, 1, 1, tzinfo=UTC)  # noqa: SLF001


def test_thor_approval_and_rollback_ignore_missing_or_irrelevant_runs() -> None:
    thor = Thor()

    asyncio.run(thor.on_typed_message("object.approval", {"correlation_id": "missing"}))
    asyncio.run(thor.on_typed_message("object.rollback", {"correlation_id": "missing"}))

    assert thor.action_runs == {}


def test_thor_rejected_approval_publishes_terminal_and_releases_lock() -> None:
    thor = Thor(bus=_bus())
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "reject-approval",
                "idempotency_key": "reject-approval-key",
                "action_type": "test.auto",
                "risk_verdict": "hil",
                "resource_id": "reject-resource",
            }
        )
    )
    assert "reject-resource" in thor._resource_locks  # noqa: SLF001
    approval = {
        "producer_principal": "Var",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "idempotency_key": run.idempotency_key,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "action_idempotency_key": run.idempotency_key,
        "rollback_contract": run.rollback_contract,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "state": "rejected",
    }

    asyncio.run(thor.on_typed_message("object.approval", approval))

    assert run.state is ActionRunState.REJECTED
    assert "reject-resource" not in thor._resource_locks  # noqa: SLF001


def test_thor_expired_approval_on_delivery_rejects_run() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock = {"now": now}
    thor = Thor(clock=lambda: clock["now"], hil_timeout_seconds=1)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "expired-approval",
                "idempotency_key": "expired-approval-key",
                "action_type": "test.auto",
                "risk_verdict": "hil",
                "resource_id": "expired-resource",
            }
        )
    )
    clock["now"] = now + timedelta(seconds=2)
    approval = {
        "producer_principal": "Var",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "idempotency_key": run.idempotency_key,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "action_idempotency_key": run.idempotency_key,
        "rollback_contract": run.rollback_contract,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "state": "approved",
    }

    asyncio.run(thor.on_typed_message("object.approval", approval))

    assert run.state is ActionRunState.REJECTED
    assert run.outcome == "approval_expired"


def test_thor_conversational_evidence_and_introspection_reflect_runs() -> None:
    thor = Thor()
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "introspect-run",
                "idempotency_key": "introspect-run-key",
                "action_type": "test.auto",
                "risk_verdict": "deny",
                "resource_id": "introspect-resource",
            }
        )
    )

    assert thor.conversation_evidence_available({}) is True
    result = asyncio.run(thor.introspect("what action runs do you retain?", {}))

    assert result.answer
    assert result.facts["total_runs"] >= 1


def test_thor_late_successful_rollback_reopens_failed_terminal() -> None:
    run = asyncio.run(
        Thor().dispatch_verdict(
            {
                "correlation_id": "rollback-late",
                "idempotency_key": "rollback-late",
                "action_type": "test.auto",
                "risk_verdict": "deny",
                "resource_id": "r",
            }
        )
    )
    run.state = ActionRunState.ROLLBACK_FAILED
    run.terminal_published = True
    thor = Thor()
    thor.action_runs[run.correlation_id] = run
    thor._resource_locks.add("r")  # noqa: SLF001
    rollback = {
        "correlation_id": run.correlation_id,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "contract": run.rollback_contract,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "state": "succeeded",
        "rollback_ref": "rollback:late",
    }

    asyncio.run(thor.on_typed_message("object.rollback", rollback))

    assert run.state is ActionRunState.ROLLED_BACK
    assert run.rollback_ref == "rollback:late"


def test_thor_terminal_rollback_redelivery_finalizes_replay_paths() -> None:
    for published in (False, True):
        thor = Thor(bus=_bus())
        run = asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": f"terminal-rollback-{published}",
                    "idempotency_key": f"terminal-rollback-{published}",
                    "action_type": "test.auto",
                    "risk_verdict": "deny",
                    "resource_id": f"terminal-resource-{published}",
                }
            )
        )
        run.terminal_published = published
        rollback = {
            "correlation_id": run.correlation_id,
            "action_type": run.action_type,
            "resource_id": run.resource_id,
            "contract": run.rollback_contract,
            "action_run_identity": action_run_identity_digest(run.to_dict()),
            "state": "failed",
        }

        asyncio.run(thor.on_typed_message("object.rollback", rollback))

        assert run.state is ActionRunState.DENY_DROPPED
