"""Kubernetes admission webhook source candidate tests."""

from __future__ import annotations

import pytest

from fdai.delivery.kubernetes.webhook_findings import admission_webhook_failure_findings


@pytest.mark.parametrize(
    ("code", "failure_class", "source_path"),
    [
        ("admission_webhook_unavailable", "backend_unavailable", "failurePolicy"),
        ("admission_webhook_tls_failure", "tls_failure", "clientConfig/caBundle"),
        ("admission_webhook_timeout", "timeout", "timeoutSeconds"),
    ],
)
def test_webhook_failure_candidate_is_structured_and_metamorphic(
    code: str,
    failure_class: str,
    source_path: str,
) -> None:
    findings = admission_webhook_failure_findings(
        [_configuration()],
        [_event(code)],
        namespace="example-app",
        evidence_complete=True,
    )

    assert len(findings) == 1
    assert findings[0]["failure_class"] == failure_class
    assert findings[0]["source_paths"] == [f"/webhooks/0/{source_path}"]
    assert findings[0]["causality"] == "candidate_only"
    assert findings[0]["affected_resource"]["name"] == "api-1"


@pytest.mark.parametrize("mutation", ["incomplete", "duplicate", "other_namespace"])
def test_webhook_failure_candidate_abstains_on_ambiguous_or_incomplete_evidence(
    mutation: str,
) -> None:
    configurations = [_configuration()]
    events = [_event("admission_webhook_timeout")]
    if mutation == "incomplete":
        configurations[0]["projection_complete"] = False
    elif mutation == "duplicate":
        configurations.append({**_configuration(), "name": "other-configuration"})
    else:
        events[0]["namespace"] = "other-app"

    assert not admission_webhook_failure_findings(
        configurations,
        events,
        namespace="example-app",
        evidence_complete=True,
    )


def test_webhook_failure_candidate_abstains_when_evidence_is_truncated() -> None:
    assert not admission_webhook_failure_findings(
        [_configuration()],
        [_event("admission_webhook_timeout")],
        namespace="example-app",
        evidence_complete=False,
    )


def _configuration() -> dict[str, object]:
    return {
        "kind": "ValidatingWebhookConfiguration",
        "name": "policy-validation",
        "namespace": "",
        "projection_complete": True,
        "webhooks": [
            {
                "name": "policy.example.io",
                "projection_complete": True,
                "failure_policy": "Fail",
                "service": {"namespace": "policy-system", "name": "policy-webhook"},
                "rules": [],
            }
        ],
    }


def _event(code: str) -> dict[str, object]:
    return {
        "namespace": "example-app",
        "reason": "FailedCreate",
        "code": code,
        "webhook_name": "policy.example.io",
        "regarding": {
            "kind": "ReplicaSet",
            "name": "api-1",
            "namespace": "example-app",
        },
    }
