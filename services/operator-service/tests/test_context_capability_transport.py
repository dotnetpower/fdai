"""Focused tests for safe opaque context-capability projection transport."""

from fdai_operator_service.redaction import redact_projection


def test_context_capability_survives_generic_redaction_without_credentials() -> None:
    token = "context-selection:" + "a" * 32

    projected = redact_projection(
        {
            "selection_token": token,
            "context_capability": {
                "selection_token": token,
                "client_secret": "must-not-cross",
                "extra": "discarded",
            },
        }
    )

    assert projected == {
        "selection_token": "[REDACTED]",
        "context_capability": {"selection_token": token},
    }
