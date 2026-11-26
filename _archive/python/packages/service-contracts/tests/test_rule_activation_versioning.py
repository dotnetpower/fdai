from __future__ import annotations

import pytest
from fdai_service_contracts.rule_activation_versioning import (
    RULE_ACTIVATION_WRITE_SCHEMA_VERSION,
    RuleActivationRecordKind,
    canonicalize_rule_activation_payload,
    canonicalize_rule_activation_typed_payload,
    decode_rule_activation_record,
    encode_rule_activation_record,
)


def test_phase_one_writes_version_one_and_reads_versions_one_and_two() -> None:
    encoded = encode_rule_activation_record(
        RuleActivationRecordKind.GENERATION,
        {"generation": {"generation_id": "generation-a"}},
    )

    assert encoded["schema_version"] == RULE_ACTIVATION_WRITE_SCHEMA_VERSION
    assert encoded["kind"] == "rule_activation.generation"
    assert decode_rule_activation_record(
        encoded,
        expected_kind=RuleActivationRecordKind.GENERATION,
    ).body == {"generation": {"generation_id": "generation-a"}}

    version_two = {**encoded, "schema_version": "2.0.0"}
    decoded = decode_rule_activation_record(
        version_two,
        expected_kind=RuleActivationRecordKind.GENERATION,
    )
    assert decoded.schema_version == "2.0.0"
    assert decoded.body == {"generation": {"generation_id": "generation-a"}}


def test_pre_version_envelope_is_read_as_legacy_version_one() -> None:
    decoded = decode_rule_activation_record(
        {"kind": "rule_activation.current", "revision": 1},
        expected_kind=RuleActivationRecordKind.POINTER,
    )

    assert decoded.schema_version == "1.0.0"
    assert decoded.body == {"revision": 1}


def test_pre_version_body_without_kind_uses_expected_legacy_kind() -> None:
    decoded = decode_rule_activation_record(
        {"generation": {"schema_version": "1.0.0"}},
        expected_kind=RuleActivationRecordKind.GENERATION,
    )

    assert decoded.schema_version == "1.0.0"
    assert decoded.body == {"generation": {"schema_version": "1.0.0"}}


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": "3.0.0", "kind": "rule_activation.result"},
        {"schema_version": "2.0.0", "kind": "rule_activation.current"},
    ],
)
def test_decode_rejects_unknown_version_or_wrong_kind(value: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        decode_rule_activation_record(
            value,
            expected_kind=RuleActivationRecordKind.RESULT,
        )


def test_encode_rejects_reserved_body_fields() -> None:
    with pytest.raises(ValueError, match="reserved"):
        encode_rule_activation_record(
            RuleActivationRecordKind.RESULT,
            {"schema_version": "2.0.0"},
        )


def test_version_two_payload_is_canonicalized_for_phase_one_models() -> None:
    assert canonicalize_rule_activation_payload(
        {"schema_version": "2.0.0", "request_id": "request-a"}
    ) == {"schema_version": "1.0.0", "request_id": "request-a"}


@pytest.mark.parametrize("kind", tuple(RuleActivationRecordKind))
def test_every_phase_one_family_keeps_v1_write_and_v2_read(
    kind: RuleActivationRecordKind,
) -> None:
    encoded = encode_rule_activation_record(kind, {"value": kind.value})
    decoded = decode_rule_activation_record(
        {**encoded, "schema_version": "2.0.0"},
        expected_kind=kind,
    )

    assert encoded["schema_version"] == "1.0.0"
    assert decoded.schema_version == "2.0.0"
    assert decoded.body == {"value": kind.value}


def test_command_canonicalization_validates_nested_payload_versions() -> None:
    command = canonicalize_rule_activation_typed_payload(
        RuleActivationRecordKind.COMMAND,
        {
            "schema_version": "2.0.0",
            "proposal": {"schema_version": "2.0.0", "request_id": "request-a"},
            "approval": {"proposal_digest": "digest-a"},
            "generation": {"schema_version": "2.0.0", "generation_id": "generation-a"},
        },
    )

    assert command["schema_version"] == "1.0.0"
    assert command["proposal"] == {
        "schema_version": "1.0.0",
        "request_id": "request-a",
    }
    assert command["generation"] == {
        "schema_version": "1.0.0",
        "generation_id": "generation-a",
    }


def test_command_canonicalization_rejects_invalid_nested_version() -> None:
    with pytest.raises(ValueError, match="schema version"):
        canonicalize_rule_activation_typed_payload(
            RuleActivationRecordKind.COMMAND,
            {
                "schema_version": "1.0.0",
                "proposal": {"schema_version": "3.0.0"},
                "generation": {"schema_version": "1.0.0"},
            },
        )
