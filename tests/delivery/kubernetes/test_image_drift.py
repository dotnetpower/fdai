"""UID-grounded image pull controller drift candidate tests."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from fdai.delivery.kubernetes.image_drift import image_pull_controller_drift_findings


def test_image_pull_drift_requires_exact_uid_chain_and_fingerprint_mismatch() -> None:
    findings = image_pull_controller_drift_findings(_resources(), evidence_complete=True)

    assert findings == (
        {
            "reason": "pod_image_pull_controller_template_drift_candidate",
            "resource": {
                "kind": "Pod",
                "name": "api-1-abc",
                "namespace": "example-app",
                "uid": "pod-uid",
            },
            "controller": {
                "kind": "Deployment",
                "name": "api",
                "namespace": "example-app",
                "uid": "deployment-uid",
            },
            "container": "api",
            "waiting_reason": "ImagePullBackOff",
            "source_paths": [
                "/spec/containers/0/image",
                "/controller/spec/template/spec/containers/image",
            ],
            "observed_image_reference_sha256": _fingerprint("registry.example/api:broken"),
            "controller_image_reference_sha256": _fingerprint("registry.example/api:v1"),
            "evidence_strength": "exact_uid_chain_and_image_fingerprint",
            "causality": "candidate_only",
            "decision": "hold",
        },
    )


def test_image_pull_drift_abstains_without_pull_failure_or_mismatch() -> None:
    healthy = deepcopy(_resources())
    healthy[0]["containers"][0]["reason"] = "CrashLoopBackOff"  # type: ignore[index]
    equal = deepcopy(_resources())
    equal[0]["pod_spec"]["containers"][0]["image_reference_sha256"] = _fingerprint(  # type: ignore[index]
        "registry.example/api:v1"
    )

    assert not image_pull_controller_drift_findings(healthy, evidence_complete=True)
    assert not image_pull_controller_drift_findings(equal, evidence_complete=True)


def test_image_pull_drift_abstains_on_incomplete_or_stale_identity() -> None:
    stale = deepcopy(_resources())
    stale[1]["uid"] = "replacement-rs-uid"

    assert not image_pull_controller_drift_findings(_resources(), evidence_complete=False)
    assert not image_pull_controller_drift_findings(stale, evidence_complete=True)


def test_image_pull_drift_abstains_on_malformed_or_ambiguous_evidence() -> None:
    malformed = deepcopy(_resources())
    malformed[0]["pod_spec"]["containers"][0]["image_reference_sha256"] = "not-a-hash"  # type: ignore[index]
    ambiguous = deepcopy(_resources())
    ambiguous.append(deepcopy(ambiguous[1]))

    assert not image_pull_controller_drift_findings(malformed, evidence_complete=True)
    assert not image_pull_controller_drift_findings(ambiguous, evidence_complete=True)


def test_image_pull_drift_is_metamorphic_to_resource_order_and_identity_rename() -> None:
    expected = image_pull_controller_drift_findings(_resources(), evidence_complete=True)
    renamed = deepcopy(_resources())
    for resource in renamed:
        resource["namespace"] = "renamed-app"

    assert (
        image_pull_controller_drift_findings(list(reversed(_resources())), evidence_complete=True)
        == expected
    )
    renamed_finding = image_pull_controller_drift_findings(renamed, evidence_complete=True)[0]
    assert renamed_finding["resource"]["namespace"] == "renamed-app"
    assert renamed_finding["controller"]["namespace"] == "renamed-app"


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Pod",
            "name": "api-1-abc",
            "namespace": "example-app",
            "uid": "pod-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {
                    "kind": "ReplicaSet",
                    "name": "api-1",
                    "uid": "rs-uid",
                    "controller": True,
                }
            ],
            "containers": [
                {
                    "name": "api",
                    "state": "waiting",
                    "reason": "ImagePullBackOff",
                }
            ],
            "pod_spec": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "api",
                        "image_reference_sha256": _fingerprint("registry.example/api:broken"),
                    }
                ],
            },
        },
        {
            "kind": "ReplicaSet",
            "name": "api-1",
            "namespace": "example-app",
            "uid": "rs-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {
                    "kind": "Deployment",
                    "name": "api",
                    "uid": "deployment-uid",
                    "controller": True,
                }
            ],
        },
        {
            "kind": "Deployment",
            "name": "api",
            "namespace": "example-app",
            "uid": "deployment-uid",
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "api",
                        "image_reference_sha256": _fingerprint("registry.example/api:v1"),
                    }
                ],
            },
        },
    ]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
