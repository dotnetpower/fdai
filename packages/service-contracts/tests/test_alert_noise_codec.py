"""Actual manifest codecs preserve signed alert identity and reject unavailable peers."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import pytest

from fdai_service_contracts import CompatibilityError, ConsumerCodec, ProducerCodec
from fdai_service_contracts.alert_noise_codec import (
    ALERT_RESULT_WIRE_BYTES,
    ALERT_WIRE_MODELS,
    AlertConsumerCodec,
    AlertProducerCodec,
)
from fdai_service_contracts.alert_noise_wire import (
    SignedAlertResult,
    sign_alert_record,
    verify_alert_record,
)
from fdai_service_contracts.codec import MAX_WIRE_BYTES
from fdai_service_contracts.manifest import load_manifest_codec

FIXTURES = Path(__file__).parent / "fixtures/services/wire-payloads.json"


@pytest.mark.parametrize(
    ("module", "symbol", "contract", "kind"),
    [
        ("fdai.delivery.alert_noise_handler", "COMMAND_CONSUMER_V1", "command", "consumer"),
        ("fdai.delivery.alert_noise_handler", "RESULT_PRODUCER_V1", "result", "producer"),
        ("fdai.runtime.alert_noise", "READINESS_PRODUCER_V1", "readiness", "producer"),
        (
            "fdai_operator_service.alert_quality_runtime",
            "COMMAND_PRODUCER_V1",
            "command",
            "producer",
        ),
        ("fdai_operator_service.alert_quality_runtime", "RESULT_CONSUMER_V1", "result", "consumer"),
        (
            "fdai_operator_service.alert_quality_runtime",
            "READINESS_CONSUMER_V1",
            "readiness",
            "consumer",
        ),
    ],
)
def test_manifest_codecs_are_bound_to_actual_runtime(module, symbol, contract, kind):
    assert getattr(importlib.import_module(module), symbol) is load_manifest_codec(
        "alert-noise-" + contract, artifact_kind=kind + "_codecs", release="N"
    )


def _payload(contract_id, release="N"):
    return next(
        row["payload"]
        for row in json.loads(FIXTURES.read_text())
        if row["contract_id"] == contract_id and row["producer_release"] == release
    )


@pytest.mark.parametrize("contract_id", ALERT_WIRE_MODELS)
@pytest.mark.parametrize("producer_release", ["N-1", "N"])
@pytest.mark.parametrize("consumer_release", ["N-1", "N"])
def test_manifest_executes_each_exact_peer_pair(contract_id, producer_release, consumer_release):
    producer = load_manifest_codec(
        contract_id, artifact_kind="producer_codecs", release=producer_release
    )
    consumer = load_manifest_codec(
        contract_id, artifact_kind="consumer_codecs", release=consumer_release
    )
    assert isinstance(producer, ProducerCodec) and isinstance(consumer, ConsumerCodec)
    payload = _payload(contract_id, producer_release)
    encoded = producer.encode(payload)
    if (producer_release, consumer_release) == ("N", "N-1"):
        with pytest.raises(CompatibilityError):
            consumer.decode(encoded)
    else:
        assert consumer.decode(encoded) == payload


@pytest.mark.parametrize("contract_id", ALERT_WIRE_MODELS)
def test_offline_marker_cannot_be_an_active_signed_record(contract_id):
    value = _payload(contract_id, "N-1")
    consumer = AlertConsumerCodec(contract_id, "N", ("0.0.0", "1.0.0"))
    assert consumer.decode_mapping(value) == value
    with pytest.raises(ValueError):
        ALERT_WIRE_MODELS[contract_id].model_validate(value)
    with pytest.raises(CompatibilityError):
        AlertProducerCodec(contract_id, "N", "1.0.0").encode(value)


@pytest.mark.parametrize("contract_id", ALERT_WIRE_MODELS)
def test_major_and_unknown_fields_have_no_silent_downgrade(contract_id):
    payload = _payload(contract_id)
    consumer = AlertConsumerCodec(contract_id, "N", ("1.0.0",))
    for field, value in (("schema_version", "2.0.0"), ("future_field", None)):
        with pytest.raises(CompatibilityError):
            consumer.decode_mapping({**payload, field: value})
    nested = next(key for key in payload if key != "signature")
    payload[nested]["schema_version"] = "2.0.0"
    with pytest.raises(CompatibilityError):
        consumer.decode_mapping(payload)


@pytest.mark.parametrize(
    "encoded",
    [b"[]", b"null", b"\xff", b'{"x":NaN}', b'{"x":1,"x":2}', b"[" * 1100, b" " * 16_385],
)
def test_decoder_rejects_malformed_or_unbounded_json(encoded):
    with pytest.raises(CompatibilityError):
        AlertConsumerCodec("alert-noise-readiness", "N", ("1.0.0",)).decode(encoded)


def test_result_retains_full_signed_content_above_generic_wire_limit():
    payload = _payload("alert-noise-result")
    command = payload["result"]["command"]
    payload["result"].update(
        status="assessment_ready",
        reason=None,
        assessment={
            "evidence_digest": "sha256:" + "a" * 64,
            "policy_digest": "sha256:" + "b" * 64,
            "tenant_ref": "tenant:example",
            "scope_ref": command["scope_ref"],
            "observed_at": command["requested_at"],
            "valid_until": command["expires_at"],
            "coverage": "complete",
            "reasons": [],
            "source_episodes": 1200,
            "notification_attempts": None,
            "confirmed_deliveries": None,
            "acknowledgements": None,
            "findings": [
                {
                    "rule_ref": f"rule:example-{index}",
                    "service_ref": "service:example",
                    "reason": "storm",
                    "guidance": "review-routing",
                    "source_episodes": 1,
                    "observed_deliveries": None,
                    "potential_recipients_lower": None,
                    "potential_recipients_upper": None,
                    "duplicate_paths": 0,
                    "protected": False,
                }
                for index in range(1200)
            ],
        },
    )
    value = SignedAlertResult.model_validate(payload)
    key = b"test-only-not-a-deployment-key-32bytes"
    signed = SignedAlertResult(result=value.result, signature=sign_alert_record(value.result, key))
    original = signed.model_dump(mode="json")
    producer = AlertProducerCodec("alert-noise-result", "N", "1.0.0")
    consumer = AlertConsumerCodec("alert-noise-result", "N", ("1.0.0",))
    encoded = producer.encode(original)
    assert MAX_WIRE_BYTES < len(encoded) < ALERT_RESULT_WIRE_BYTES
    decoded = consumer.decode(encoded)
    assert decoded == original == consumer.decode_mapping(original)
    restored = SignedAlertResult.model_validate(decoded)
    verify_alert_record(restored.result, restored.signature, key)
    tampered = copy.deepcopy(decoded)
    tampered["result"]["assessment"]["source_episodes"] += 1
    altered = SignedAlertResult.model_validate(consumer.decode_mapping(tampered))
    with pytest.raises(ValueError, match="authentication failed"):
        verify_alert_record(altered.result, altered.signature, key)
    original["result"]["assessment"]["findings"] *= 4
    with pytest.raises(CompatibilityError):
        producer.encode(original)
    with pytest.raises(CompatibilityError):
        consumer.decode_mapping(original)
