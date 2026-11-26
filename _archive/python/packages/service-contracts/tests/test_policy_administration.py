from __future__ import annotations

from datetime import UTC, datetime

from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
    PolicyRevisionSignature,
    PolicyValidationResult,
)


def test_policy_revision_signature_is_backward_compatible_and_retains_raw_signature() -> None:
    legacy = _record(signature=None).model_dump(mode="json", exclude={"signature"})
    parsed_legacy = PolicyRevisionRecord.model_validate(legacy)
    signature = PolicyRevisionSignature(
        key_id="https://fdai-example.vault.azure.net/keys/policy-signing/v1",
        algorithm="RS256",
        signature_base64="raw-key-vault-signature",
    )
    parsed_signed = PolicyRevisionRecord.model_validate(
        _record(signature=signature).model_dump(mode="json")
    )

    assert parsed_legacy.signature is None
    assert parsed_signed.signature == signature
    assert parsed_signed.signature.signed_message_format == "fdai.policy-revision.v1"
    assert parsed_signed.signature.digest_algorithm == "SHA-256"


def _record(signature: PolicyRevisionSignature | None) -> PolicyRevisionRecord:
    return PolicyRevisionRecord(
        revision_id="admission:example",
        policy_kind=PolicyKind.ADMISSION,
        content_digest="sha256:" + "a" * 64,
        content=AdmissionPolicyContent(
            rego="package fdai.policy\nallow := true\n",
            action_type_modes={},
            policy_tests=({"rego": "package fdai.policy\n test_allow if { allow }\n"},),
        ),
        signature_ref=signature.key_id if signature is not None else "legacy-signature",
        signature=signature,
        author_principal="policy-admin",
        reason="Reviewed policy change for a bounded installation scope.",
        created_at=datetime.now(UTC),
        validation=PolicyValidationResult(
            rego_valid=True,
            release_maximums_valid=True,
            policy_tests_valid=True,
            validation_digest="sha256:" + "b" * 64,
        ),
        diff_digest="sha256:" + "c" * 64,
    )
