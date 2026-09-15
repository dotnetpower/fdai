"""Synthetic request history, exact terminal authentication and current-access boundaries."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fdai_operator_service.alert_quality_command import alert_request_ref, command_from_record
from fdai_operator_service.alert_quality_history import (
    AlertQualityRequestHistory,
    StateKvAlertQualityRequestSource,
)
from fdai_operator_service.alert_quality_records import alert_quality_requester_ref
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseResult,
    SignedAlertResult,
    sign_alert_record,
)

from .test_alert_quality import (
    HEADERS,
    NOW,
    OTHER_PRINCIPAL,
    PRINCIPAL,
    SCOPE,
    _assessment,
    _client,
    _harness,
    _State,
)

KEY = b"test-only-alert-history-transport-key"


class HistoryState(_State):
    """Test-only read primitive with the same exact principal/scope query as the real store."""

    async def recent_alert_quality_requests(self, *, principal_id, scope_ref, limit):
        rows = [
            row
            for key, row in self.records.items()
            if key.startswith("operator-proposal:operations:")
            and row["principal_id"] == principal_id
            and row["payload"]["payload"]["scope_ref"] == scope_ref
        ]
        return tuple(copy.deepcopy(rows[-limit:][::-1]))


def acceptance(state, *, key="example-key", subject=PRINCIPAL, scope=SCOPE):
    ref = alert_request_ref(subject, key)
    outer = {
        "principal_id": subject,
        "idempotency_key": ref,
        "operation": "alert_noise.assess",
        "payload": {
            "scope_ref": scope,
            "request_idempotency_key": key,
            "requester_ref": alert_quality_requester_ref(subject, scope),
        },
    }
    record = {
        **outer,
        "payload": outer,
        "accepted_at": NOW.isoformat(),
        "dispatch_status": "pending",
    }
    state.records["operator-proposal:operations:" + hashlib.sha256(ref.encode()).hexdigest()] = (
        record
    )
    return record


def terminal(state, record, *, held=False):
    command = command_from_record(record)
    result = AlertNoiseResult(
        command=command,
        command_digest=digest_record(command),
        recorded_at=NOW,
        status="held" if held else "assessment_ready",
        reason="source_unavailable" if held else None,
        assessment=None if held else _assessment(scope_ref=command.scope_ref),
    )
    signed = SignedAlertResult(result=result, signature=sign_alert_record(result, KEY)).model_dump(
        mode="json"
    )
    state.records["operator-alert-quality-result:" + command.request_ref] = signed
    return signed


@pytest.mark.parametrize("held", [False, True])
async def test_exact_terminal_survives_new_reader_without_projecting_as_effect(held):
    state = HistoryState()
    record = acceptance(state)
    source = StateKvAlertQualityRequestSource(state, transport_key=KEY, clock=lambda: NOW)
    waiting = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE)
    assert waiting.requests[0].status == "pending"
    terminal(state, record, held=held)
    snapshot = copy.deepcopy(state.records)
    restarted = StateKvAlertQualityRequestSource(state, transport_key=KEY, clock=lambda: NOW)
    result = await restarted.read(
        principal_id=PRINCIPAL, scope_ref=SCOPE, request_key="example-key"
    )
    assert result.requests[0].status == ("held" if held else "assessment_ready")
    assert result.requests[0].result_recorded_at == NOW
    assert not result.execution_authority and not result.requests[0].execution_authority
    assert state.records == snapshot


@pytest.mark.parametrize("dispatch", ["pending", "claimed", "published", "rejected"])
async def test_expired_or_rejected_without_terminal_is_unconfirmed_not_no_effect(dispatch):
    state = HistoryState()
    acceptance(state)["dispatch_status"] = dispatch
    source = StateKvAlertQualityRequestSource(
        state, transport_key=KEY, clock=lambda: NOW + timedelta(minutes=5)
    )
    result = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE)
    row = result.requests[0]
    assert row.status == "unconfirmed" and row.result_recorded_at is None and row.plan is None


@pytest.mark.parametrize("change", ["signature", "command", "future", "identity", "key"])
async def test_history_never_projects_forged_or_cross_request_claims(change):
    state = HistoryState()
    record = acceptance(state)
    signed = terminal(state, record)
    if change == "signature":
        signed["signature"] = "sha256:" + "a" * 64
    elif change == "command":
        signed["result"]["command"]["request_ref"] = "request:other"
    elif change == "future":
        source_clock = NOW - timedelta(seconds=1)
    elif change == "identity":
        record["principal_id"] = OTHER_PRINCIPAL
    else:
        record["payload"]["payload"]["request_idempotency_key"] = "different"
    source = StateKvAlertQualityRequestSource(
        state, transport_key=KEY, clock=lambda: source_clock if change == "future" else NOW
    )
    with pytest.raises((ValueError, RuntimeError)):
        await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE, request_key="example-key")


async def test_bounded_history_never_infers_a_complete_page_or_other_principal():
    state = HistoryState()
    for index in range(26):
        acceptance(state, key=f"key-{index}")
    acceptance(state, key="other", subject=OTHER_PRINCIPAL)
    source = StateKvAlertQualityRequestSource(state, transport_key=KEY, clock=lambda: NOW)
    result = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE)
    assert result.truncated and len(result.requests) == 25
    assert all(row.request_key != "other" for row in result.requests)
    exact = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE, request_key="key-0")
    assert len(exact.requests) == 1 and not exact.truncated
    empty = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE, request_key="absent")
    assert empty.requests == ()


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?scope_ref=",
        "?scope_ref=scope:one&scope_ref=scope:one",
        "?scope_ref=scope:one&request_key=",
        "?scope_ref=scope:one&request_key=a&request_key=b",
        "?scope_ref=scope:one&unknown=x",
    ],
)
async def test_history_query_is_closed_and_scope_is_required(query):
    _, _, dependencies = _harness()
    async with _client(dependencies) as client:
        result = await client.get("/alert-quality/requests" + query, headers=HEADERS)
    assert result.status_code == 400


async def test_history_api_requires_current_scope_even_after_read():
    _, _, dependencies = _harness()
    state = HistoryState()
    record = acceptance(state)
    terminal(state, record, held=True)
    source = StateKvAlertQualityRequestSource(state, transport_key=KEY, clock=lambda: NOW)
    dependencies = replace(dependencies, request_source=source)
    async with _client(dependencies) as client:
        response = await client.get(
            "/alert-quality/requests", params={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["requests"][0]["status"] == "held"

    class RevokingSource:
        async def read(self, **kwargs):
            value = await source.read(**kwargs)
            object.__setattr__(dependencies, "principal_scopes", {})
            return value

    dependencies = replace(dependencies, request_source=RevokingSource())
    async with _client(dependencies) as client:
        response = await client.get(
            "/alert-quality/requests", params={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 403


async def test_missing_source_is_unavailable_not_empty_history():
    _, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get(
            "/alert-quality/requests", params={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 503


def test_console_history_fixture_has_exact_backend_plan_and_baseline_bindings():
    path = (
        Path(__file__).resolve().parents[3]
        / "console/src/routes/alert-quality.history.fixture.json"
    )
    history = AlertQualityRequestHistory.model_validate_json(path.read_text(encoding="utf-8"))
    entry = history.requests[0]
    assert entry.detail is not None and entry.plan is not None
    entry.detail.require_plan(entry.plan)
