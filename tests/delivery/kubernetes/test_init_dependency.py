"""Init-container dependency wait candidate tests."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from fdai.delivery.kubernetes.init_dependency import init_dependency_wait_findings


def test_init_dependency_requires_exact_chain_and_targeted_absence() -> None:
    finding = init_dependency_wait_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=True
    )[0]
    assert finding["resource"]["uid"] == "deployment-uid"
    assert finding["affected_pod"]["uid"] == "pod-uid"
    assert finding["dependency"]["name"] == "database"
    assert finding["decision"] == "hold"


def test_init_dependency_abstains_on_truncated_present_or_conflicting_receipt() -> None:
    assert not init_dependency_wait_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=False
    )
    assert not init_dependency_wait_findings(
        _resources(), [_receipt("present")], evidence_complete=True
    )
    assert not init_dependency_wait_findings(
        _resources(), [_receipt("present"), _receipt("confirmed_absent")], evidence_complete=True
    )


def test_init_dependency_abstains_on_uid_or_command_drift() -> None:
    uid_drift = deepcopy(_resources())
    uid_drift[1]["uid"] = "replacement-uid"
    command_drift = deepcopy(_resources())
    command_drift[1]["pod_template"]["init_containers"][0]["command_sha256"] = _digest("changed")  # type: ignore[index]
    assert not init_dependency_wait_findings(
        uid_drift, [_receipt("confirmed_absent")], evidence_complete=True
    )
    assert not init_dependency_wait_findings(
        command_drift, [_receipt("confirmed_absent")], evidence_complete=True
    )


def test_init_dependency_abstains_without_running_single_init() -> None:
    stopped = deepcopy(_resources())
    stopped[0]["init_containers"][0]["state"] = "terminated"  # type: ignore[index]
    assert not init_dependency_wait_findings(
        stopped, [_receipt("confirmed_absent")], evidence_complete=True
    )


def test_init_dependency_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = init_dependency_wait_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=True
    )
    resources = deepcopy(_resources())
    for resource in resources:
        resource["namespace"] = "renamed-app"
        key = "pod_spec" if resource["kind"] == "Pod" else "pod_template"
        resource[key]["init_containers"][0]["service_dependencies"][0]["namespace"] = "renamed-app"  # type: ignore[index]
    receipt = _receipt("confirmed_absent")
    receipt["namespace"] = "renamed-app"
    assert (
        init_dependency_wait_findings(
            list(reversed(_resources())), [_receipt("confirmed_absent")], evidence_complete=True
        )
        == expected
    )
    assert (
        init_dependency_wait_findings(resources, [receipt], evidence_complete=True)[0]["resource"][
            "namespace"
        ]
        == "renamed-app"
    )


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Pod",
            "namespace": "example-app",
            "name": "api-1",
            "uid": "pod-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {"kind": "ReplicaSet", "name": "api-rs", "uid": "rs-uid", "controller": True}
            ],
            "init_status_projection_complete": True,
            "init_containers": [{"name": "wait-db", "state": "running"}],
            "pod_spec": _template(),
        },
        {
            "kind": "ReplicaSet",
            "namespace": "example-app",
            "name": "api-rs",
            "uid": "rs-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {"kind": "Deployment", "name": "api", "uid": "deployment-uid", "controller": True}
            ],
            "pod_template": _template(),
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "uid": "deployment-uid",
            "pod_template": _template(),
        },
    ]


def _template() -> dict[str, object]:
    return {
        "projection_complete": True,
        "init_containers": [
            {
                "name": "wait-db",
                "command_sha256": _digest("wait"),
                "wait_loop": True,
                "service_dependencies": [{"namespace": "example-app", "service": "database"}],
            }
        ],
    }


def _receipt(status: str) -> dict[str, object]:
    return {"namespace": "example-app", "name": "database", "status": status}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
