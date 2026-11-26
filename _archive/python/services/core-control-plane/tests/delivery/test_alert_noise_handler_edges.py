"""Alert-noise handler fail-closed edge tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fdai.delivery.alert_noise_handler import AlertNoiseAgentHandler
from fdai.delivery.alert_noise_retirement import ALERT_RESULT_PREFIX
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    SignedAlertCommand,
    sign_alert_record,
)

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.delivery.test_alert_noise_retirement import _KEY, _NOW, _command, _handler, _held


class _PeriodSource:
    def __init__(self, evidence: AlertEvidence) -> None:
        self.evidence = evidence

    async def collect(self, *, now: datetime) -> AlertEvidence:
        return self.evidence

    async def collect_period(self, *, now: datetime, period_seconds: int) -> AlertEvidence:
        return self.evidence


def test_handler_rejects_weak_transport_key() -> None:
    with pytest.raises(ValueError, match="transport key"):
        AlertNoiseAgentHandler(
            store=InMemoryStateStore(),
            sources={},
            principals={},
            policy=NoisePolicy(),
            transport_key=b"short",
        )


async def test_observe_fails_closed_for_bad_period_source_and_scope(
    evidence: AlertEvidence,
) -> None:
    store = InMemoryStateStore()
    live = evidence.model_copy(
        update={
            "stamp": evidence.stamp.model_copy(update={"synthetic": False}),
            "window_end": _NOW - timedelta(seconds=1),
        }
    )
    handler = AlertNoiseAgentHandler(
        store=store,
        sources={"scope:example": _PeriodSource(live)},
        principals={"principal:example": frozenset({"scope:example"})},
        policy=NoisePolicy(),
        transport_key=_KEY,
        clock=lambda: _NOW,
    )
    command = _command("request:period", period_seconds=3600)

    signal = await handler.observe(
        {
            "producer_principal": "Huginn",
            "alert_noise": SignedAlertCommand(
                command=command, signature=sign_alert_record(command, _KEY)
            ).model_dump(mode="json"),
        }
    )

    assert signal["reason"] == "source_unavailable"
    assert signal["evidence_digest"] is None
    scoped = live.model_copy(
        update={"stamp": live.stamp.model_copy(update={"scope_ref": "scope:other"})}
    )
    handler.sources["scope:example"] = _PeriodSource(scoped)
    with pytest.raises(ValueError, match="source scope mismatch"):
        await handler.observe(
            {
                "producer_principal": "Huginn",
                "alert_noise": SignedAlertCommand(
                    command=_command("request:scope"),
                    signature=sign_alert_record(_command("request:scope"), _KEY),
                ).model_dump(mode="json"),
            }
        )


@pytest.mark.parametrize(
    ("name", "command", "principals", "expected"),
    [
        (
            "expired",
            _command("request:expired", requested_at=_NOW - timedelta(minutes=10)),
            {"principal:example": frozenset({"scope:example"})},
            "request_expired",
        ),
        ("denied", _command("request:denied"), {}, "scope_denied"),
        (
            "missing",
            _command(
                "request:missing",
                operation="alert_noise.propose",
                evidence_digest="sha256:" + "0" * 64,
                treatment=AlertTreatment(
                    kind="routing",
                    target_ref="rule:example",
                    remove_group_ref="group:old",
                    replacement_group_ref="group:new",
                ),
            ),
            {"principal:example": frozenset({"scope:example"})},
            "evidence_not_retained",
        ),
        (
            "source",
            _command("request:source"),
            {"principal:example": frozenset({"scope:example"})},
            "source_unavailable",
        ),
    ],
)
async def test_observe_records_specific_fail_closed_reason_without_source_fallback(
    name: str,
    command: AlertNoiseCommand,
    principals: dict[str, frozenset[str]],
    expected: str,
) -> None:
    handler = AlertNoiseAgentHandler(
        store=InMemoryStateStore(),
        sources={},
        principals=principals,
        policy=NoisePolicy(),
        transport_key=_KEY,
        clock=lambda: _NOW,
    )

    signal = await handler.observe(
        {
            "producer_principal": "Huginn",
            "alert_noise": SignedAlertCommand(
                command=command, signature=sign_alert_record(command, _KEY)
            ).model_dump(mode="json"),
        }
    )

    assert signal["correlation_id"] == command.request_ref
    assert signal["reason"] == expected
    assert signal["execution_authority"] is False


async def test_observe_replay_detects_same_request_ref_identity_conflict() -> None:
    store = InMemoryStateStore()
    handler = _handler(store)
    first = _command("request:conflict")
    await handler.observe(
        {
            "producer_principal": "Huginn",
            "alert_noise": SignedAlertCommand(
                command=first, signature=sign_alert_record(first, _KEY)
            ).model_dump(mode="json"),
        }
    )
    changed = _command("request:conflict", requested_at=_NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="identity conflict"):
        await handler.observe(
            {
                "producer_principal": "Huginn",
                "alert_noise": SignedAlertCommand(
                    command=changed, signature=sign_alert_record(changed, _KEY)
                ).model_dump(mode="json"),
            }
        )


async def test_plan_refuses_when_observation_evidence_disappears(
    evidence: AlertEvidence,
) -> None:
    store = InMemoryStateStore()
    handler = _handler(store)
    live = evidence.model_copy(
        update={"stamp": evidence.stamp.model_copy(update={"synthetic": False})}
    )
    digest = digest_record(live)
    command = _command("request:missing-evidence")
    signal = {
        "kind": "alert_noise",
        "correlation_id": command.request_ref,
        "idempotency_key": "alert-noise:observed:" + command.request_ref,
        "resource_id": command.scope_ref,
        "command": command.model_dump(mode="json"),
        "command_digest": digest_record(command),
        "evidence_digest": digest,
        "reason": None,
        "execution_authority": False,
    }
    await store.write_state("alert-noise:observation:" + command.request_ref, signal)

    with pytest.raises(ValueError, match="evidence disappeared"):
        await handler.plan({**signal, "producer_principal": "Heimdall"})


async def test_plan_requires_heimdall_lineage_and_detects_result_conflicts() -> None:
    store = InMemoryStateStore()
    handler = _handler(store)
    command = _command("request:plan-conflict")
    signal = {
        "kind": "alert_noise",
        "correlation_id": command.request_ref,
        "idempotency_key": "alert-noise:observed:" + command.request_ref,
        "resource_id": command.scope_ref,
        "command": command.model_dump(mode="json"),
        "command_digest": digest_record(command),
        "evidence_digest": None,
        "reason": "source_unavailable",
        "execution_authority": False,
    }
    await store.write_state("alert-noise:observation:" + command.request_ref, signal)

    with pytest.raises(ValueError, match="authenticated Heimdall"):
        await handler.plan({**signal, "producer_principal": "Huginn"})
    with pytest.raises(ValueError, match="observation lineage"):
        await handler.plan({**signal, "producer_principal": "Heimdall", "reason": "changed"})

    result = _held(command)
    await store.write_state(
        ALERT_RESULT_PREFIX + command.request_ref,
        {
            "result": _held(_command("request:other")),
            "publication_state": "published",
            "revision": 1,
        },
    )
    with pytest.raises(ValueError, match="identity conflict"):
        await handler.plan({**signal, "producer_principal": "Heimdall"})
    await store.write_state(
        ALERT_RESULT_PREFIX + command.request_ref,
        {"result": result, "publication_state": "published", "revision": 1},
    )
    assert await handler.plan({**signal, "producer_principal": "Heimdall"}) == result
