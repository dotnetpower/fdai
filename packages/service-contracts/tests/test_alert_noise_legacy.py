"""Unreleased alert-noise 1.0.0 records are authenticated exactly and never become current."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_legacy import (
    LEGACY_ALERT_CONTRACT_REASON,
    _AlertChangePlanV100,
    _AlertNoiseResultV100,
    _SignedAlertResultV100,
    decode_legacy_alert_plan,
    decode_legacy_alert_result,
    decode_legacy_signed_alert_result,
)
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertTreatment
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    AlertNoiseResult,
    SignedAlertResult,
    sign_alert_record,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
KEY = b"test-only-alert-legacy-transport-key"
SCHEMAS = Path(__file__).resolve().parents[1] / "src/fdai_service_contracts/schemas"


def _plan() -> AlertChangePlan:
    return AlertChangePlan(
        action_type="ops.update-alert-routing",
        tenant_ref="tenant:example",
        scope_ref="scope:example",
        requester_ref="principal:example",
        evidence_digest="sha256:" + "1" * 64,
        policy_digest="sha256:" + "2" * 64,
        target_revision="sha256:" + "3" * 64,
        treatment=AlertTreatment(
            kind="routing",
            target_ref="rule:example",
            replacement_group_ref="group:new",
            remove_group_ref="group:old",
        ),
        service_refs=("service:example",),
        lock_refs=("lock:example",),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        max_execution_seconds=60,
        max_observation_seconds=60,
        max_recovery_seconds=60,
        rollback_ref="sha256:" + "4" * 64,
    )


def _result() -> AlertNoiseResult:
    command = AlertNoiseCommand(
        operation="alert_noise.assess",
        request_ref="request:example",
        requester_ref="principal:example",
        scope_ref="scope:example",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    return AlertNoiseResult(
        command=command,
        command_digest=digest_record(command),
        recorded_at=NOW + timedelta(seconds=1),
        status="held",
        reason="source_unavailable",
    )


def _legacy_plan() -> dict[str, Any]:
    return {
        **_plan().model_dump(mode="json"),
        "schema_version": "1.0.0",
        "execution_path": "pr_manual",
    }


def _legacy_signed() -> dict[str, Any]:
    archived = _AlertNoiseResultV100.model_validate(
        {**_result().model_dump(mode="json"), "schema_version": "1.0.0"}
    )
    return {
        "result": archived.model_dump(mode="json"),
        "signature": sign_alert_record(archived, KEY),
    }


def _render(model: type[Any], name: str, archived_names: dict[str, str]) -> dict[str, Any]:
    text = json.dumps(model.model_json_schema())
    for archived, original in archived_names.items():
        text = text.replace(archived, original)
    schema: dict[str, Any] = json.loads(text)
    schema["$id"] = f"https://fdai.dev/service-contracts/{name}/1.0.0"
    return schema


def _field_orders(schema: dict[str, Any]) -> dict[str, list[str]]:
    orders = {name: list(item.get("properties", {})) for name, item in schema["$defs"].items()}
    return {**orders, "$root": list(schema.get("properties", {}))}


def test_archived_models_render_the_preserved_1_0_0_schemas_exactly() -> None:
    plan = _render(
        _AlertChangePlanV100, "alert-noise-plan", {"_AlertChangePlanV100": "AlertChangePlan"}
    )
    result = _render(
        _SignedAlertResultV100,
        "alert-noise-result",
        {
            "_SignedAlertResultV100": "SignedAlertResult",
            "_AlertNoiseResultV100": "AlertNoiseResult",
            "_AlertChangePlanV100": "AlertChangePlan",
        },
    )

    for rendered, name in ((plan, "alert-noise-plan"), (result, "alert-noise-result")):
        preserved = json.loads((SCHEMAS / name / "1.0.0.json").read_text(encoding="utf-8"))
        assert rendered == preserved
        assert _field_orders(rendered) == _field_orders(preserved)


def test_current_records_are_never_recognized_as_legacy() -> None:
    plan, result = _plan(), _result()
    signed = SignedAlertResult(result=result, signature=sign_alert_record(result, KEY))

    assert (
        decode_legacy_alert_plan(plan.model_dump(mode="json"), expected_digest=digest_record(plan))
        is None
    )
    assert decode_legacy_alert_result(result.model_dump(mode="json")) is None
    assert decode_legacy_signed_alert_result(signed.model_dump(mode="json"), key=KEY) is None
    for raw in (None, "1.0.0", {"schema_version": "0.0.0"}):
        assert decode_legacy_alert_result(raw) is None


def test_legacy_plan_is_recognized_only_with_its_exact_digest() -> None:
    raw = _legacy_plan()
    digest = digest_record(_AlertChangePlanV100.model_validate(raw))

    retired = decode_legacy_alert_plan(raw, expected_digest=digest)

    assert retired is not None and retired.digest == digest
    assert not isinstance(retired, AlertChangePlan)
    with pytest.raises(ValueError, match="digest"):
        decode_legacy_alert_plan(raw, expected_digest=digest_record(_plan()))
    for changed in ({"execution_path": "direct_api"}, {"quorum_required": 1}, {"extra": "field"}):
        with pytest.raises(ValueError, match="legacy alert record"):
            decode_legacy_alert_plan({**raw, **changed}, expected_digest=digest)


def test_legacy_signed_result_requires_its_original_signature() -> None:
    signed = _legacy_signed()

    retired = decode_legacy_signed_alert_result(signed, key=KEY)

    assert retired is not None
    assert retired.command == _result().command
    assert retired.recorded_at == _result().recorded_at
    assert retired.record_digest == digest_record(
        _AlertNoiseResultV100.model_validate(signed["result"])
    )
    assert decode_legacy_alert_result(signed["result"]) == retired
    with pytest.raises(ValueError, match="authentication"):
        decode_legacy_signed_alert_result({**signed, "signature": "sha256:" + "a" * 64}, key=KEY)
    with pytest.raises(ValueError, match="authentication"):
        decode_legacy_signed_alert_result(signed, key=b"x" * 32)


def test_marker_without_the_exact_legacy_shape_is_invalid_without_echoing_content() -> None:
    raw = {**_legacy_signed()["result"], "reason": None, "command": {"request_ref": "private"}}

    with pytest.raises(ValueError) as error:
        decode_legacy_alert_result(raw)

    assert str(error.value) == "legacy alert record is invalid"
    assert LEGACY_ALERT_CONTRACT_REASON == "legacy_contract_retired"
