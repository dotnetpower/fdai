"""Kubernetes direct admission condition finding tests."""

from __future__ import annotations

from fdai.delivery.kubernetes.admission_conditions import admission_condition_findings


def test_admission_condition_is_explicit_direct_candidate_evidence() -> None:
    findings = admission_condition_findings(
        [
            {
                "kind": "ReplicaSet",
                "name": "api-1",
                "namespace": "example-app",
                "admission_condition_projection_complete": True,
                "admission_conditions": [
                    {
                        "type": "ReplicaFailure",
                        "status": "True",
                        "reason": "FailedCreate",
                        "code": "admission_webhook_tls_failure",
                        "webhook_name": "policy.example.io",
                        "source_index": 2,
                    }
                ],
            }
        ],
        evidence_complete=True,
    )

    assert findings == (
        {
            "reason": "kubernetes_condition_admission_webhook_tls_failure",
            "resource": {
                "kind": "ReplicaSet",
                "name": "api-1",
                "namespace": "example-app",
            },
            "source_paths": ["/status/conditions/2"],
            "condition_type": "ReplicaFailure",
            "condition_reason": "FailedCreate",
            "evidence_strength": "direct_resource_condition",
            "causality": "candidate_only",
            "decision": "hold",
            "webhook_name": "policy.example.io",
        },
    )


def test_admission_condition_abstains_on_incomplete_evidence() -> None:
    resource = {
        "admission_condition_projection_complete": True,
        "admission_conditions": [{"code": "admission_webhook_timeout", "source_index": 0}],
    }

    assert not admission_condition_findings([resource], evidence_complete=False)
    resource["admission_condition_projection_complete"] = False
    assert not admission_condition_findings([resource], evidence_complete=True)
