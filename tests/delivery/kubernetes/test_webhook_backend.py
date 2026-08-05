"""Targeted webhook backend absence candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.webhook_backend import missing_webhook_backend_findings


def test_missing_webhook_backend_requires_targeted_absence_receipt() -> None:
    findings = missing_webhook_backend_findings(
        [_configuration()], [_receipt("confirmed_absent")], evidence_complete=True
    )

    assert findings == (
        {
            "reason": "admission_webhook_backend_service_missing_candidate",
            "resource": {"kind": "ValidatingWebhookConfiguration", "name": "policy"},
            "source_paths": ["/webhooks/0/clientConfig/service"],
            "webhook_name": "policy.example.io",
            "failure_policy": "Fail",
            "service": {"namespace": "policy-system", "name": "policy-webhook"},
            "affected_namespaces": ["example-app"],
            "scope_source_path": "/webhooks/0/namespaceSelector",
            "evidence_strength": "targeted_service_absence_receipt",
            "causality": "candidate_only",
            "decision": "hold",
        },
    )


def test_missing_webhook_backend_abstains_on_present_or_incomplete_evidence() -> None:
    assert not missing_webhook_backend_findings(
        [_configuration()], [_receipt("present")], evidence_complete=True
    )
    assert not missing_webhook_backend_findings(
        [_configuration()], [_receipt("confirmed_absent")], evidence_complete=False
    )


def test_missing_webhook_backend_abstains_on_conflicting_or_malformed_receipts() -> None:
    conflicting = [_receipt("confirmed_absent"), _receipt("present")]
    malformed = _receipt("confirmed_absent")
    malformed.pop("namespace")

    assert not missing_webhook_backend_findings(
        [_configuration()], conflicting, evidence_complete=True
    )
    assert not missing_webhook_backend_findings(
        [_configuration()], [malformed], evidence_complete=True
    )


def test_missing_webhook_backend_abstains_on_incomplete_configuration() -> None:
    configuration = _configuration()
    configuration["projection_complete"] = False

    assert not missing_webhook_backend_findings(
        [configuration], [_receipt("confirmed_absent")], evidence_complete=True
    )


def test_missing_webhook_backend_omits_ambiguous_impact_scope() -> None:
    configuration = _configuration()
    configuration["webhooks"][0]["namespace_selector"] = {"present": True}  # type: ignore[index]

    finding = missing_webhook_backend_findings(
        [configuration], [_receipt("confirmed_absent")], evidence_complete=True
    )[0]

    assert "affected_namespaces" not in finding
    assert "scope_source_path" not in finding


def test_missing_webhook_backend_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = missing_webhook_backend_findings(
        [_configuration()], [_receipt("confirmed_absent")], evidence_complete=True
    )
    renamed_configuration = deepcopy(_configuration())
    renamed_configuration["webhooks"][0]["service"]["namespace"] = "renamed-system"  # type: ignore[index]
    renamed_receipt = _receipt("confirmed_absent")
    renamed_receipt["namespace"] = "renamed-system"

    assert (
        missing_webhook_backend_findings(
            list(reversed([_configuration()])),
            list(reversed([_receipt("confirmed_absent")])),
            evidence_complete=True,
        )
        == expected
    )
    renamed = missing_webhook_backend_findings(
        [renamed_configuration], [renamed_receipt], evidence_complete=True
    )
    assert renamed[0]["service"]["namespace"] == "renamed-system"


def _configuration() -> dict[str, object]:
    return {
        "kind": "ValidatingWebhookConfiguration",
        "name": "policy",
        "projection_complete": True,
        "webhooks": [
            {
                "name": "policy.example.io",
                "projection_complete": True,
                "failure_policy": "Fail",
                "namespace_selector": {"present": True, "exact_namespace": "example-app"},
                "service": {"namespace": "policy-system", "name": "policy-webhook"},
            }
        ],
    }


def _receipt(status: str) -> dict[str, object]:
    return {"namespace": "policy-system", "name": "policy-webhook", "status": status}
