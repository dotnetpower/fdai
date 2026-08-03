"""Deterministic Kubernetes admission failure classification tests."""

from __future__ import annotations

import pytest

from fdai.delivery.kubernetes.admission_events import classify_admission_failure


@pytest.mark.parametrize(
    ("detail", "expected_code"),
    [
        ("tls: failed to verify certificate: x509: certificate is not valid", "tls_failure"),
        ("context deadline exceeded", "timeout"),
        ("dial tcp: connection refused", "unavailable"),
    ],
)
def test_classifies_failed_webhook_calls(detail: str, expected_code: str) -> None:
    failure = classify_admission_failure(
        reason="FailedCreate",
        message=f'failed calling webhook "policy.example.io": {detail}',
    )

    assert failure is not None
    assert failure.code == f"admission_webhook_{expected_code}"
    assert failure.webhook_name == "policy.example.io"


def test_classifies_bounded_pod_security_details() -> None:
    failure = classify_admission_failure(
        reason="FailedCreate",
        message=(
            'pods "api-1" is forbidden: violates PodSecurity "restricted:latest": '
            "allowPrivilegeEscalation != false, runAsNonRoot != true"
        ),
    )

    assert failure is not None
    assert failure.code == "pod_security_admission_rejected"
    assert failure.pod_security_profile == "restricted"
    assert failure.pod_security_version == "latest"
    assert failure.pod_security_violations == (
        "allow_privilege_escalation",
        "run_as_non_root",
    )


@pytest.mark.parametrize("reason", ["Normal", "Scheduled", "Unhealthy"])
def test_does_not_classify_informational_admission_text(reason: str) -> None:
    assert (
        classify_admission_failure(
            reason=reason,
            message=(
                'observer reported failed calling webhook "policy.example.io": '
                "context deadline exceeded"
            ),
        )
        is None
    )


def test_does_not_classify_unbounded_or_malformed_webhook_identity() -> None:
    assert (
        classify_admission_failure(
            reason="FailedCreate",
            message='failed calling webhook "not valid": context deadline exceeded',
        )
        is None
    )
    assert (
        classify_admission_failure(
            reason="FailedCreate",
            message=f'failed calling webhook "{"a" * 254}": context deadline exceeded',
        )
        is None
    )


def test_does_not_treat_pod_security_guidance_as_rejection() -> None:
    assert (
        classify_admission_failure(
            reason="FailedCreate",
            message='guidance: violates PodSecurity "restricted:latest"',
        )
        is None
    )
