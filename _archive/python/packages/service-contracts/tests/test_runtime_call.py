"""Runtime-call identity must remain exact across independently released services."""

from fdai_service_contracts.runtime_call import (
    RUNTIME_CALL_MAPPING_ID,
    RUNTIME_CALL_MAPPING_REVISION,
    RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
    RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
    RUNTIME_CALL_VERIFICATION_METHOD,
)


def test_runtime_call_relationship_identity_is_content_addressed() -> None:
    assert RUNTIME_CALL_MAPPING_ID == "runtime-call-endpoint-identity"
    assert RUNTIME_CALL_MAPPING_REVISION == "1.1.0"
    assert RUNTIME_CALL_SOURCE_SCHEMA_VERSION == "fdai.runtime-call-observation@1.1.0"
    assert RUNTIME_CALL_SOURCE_SCHEMA_DIGEST == (
        "sha256:536d6040b381f005408960783ef4f68ef6de8c61411904ae7c05b5b5bdec4dc9"
    )
    assert RUNTIME_CALL_VERIFICATION_METHOD == "deterministic-cross-check"
