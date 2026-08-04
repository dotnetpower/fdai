"""Missing ConfigMap mount candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.configmap_mount import missing_configmap_mount_findings


def test_missing_configmap_requires_mounted_volume_and_targeted_absence() -> None:
    finding = missing_configmap_mount_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=True
    )[0]
    assert finding["configmap"]["name"] == "settings"
    assert finding["volume"] == "config"
    assert finding["decision"] == "hold"


def test_missing_configmap_abstains_on_truncated_present_or_conflicting_receipt() -> None:
    assert not missing_configmap_mount_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=False
    )
    assert not missing_configmap_mount_findings(
        _resources(), [_receipt("present")], evidence_complete=True
    )
    assert not missing_configmap_mount_findings(
        _resources(), [_receipt("present"), _receipt("confirmed_absent")], evidence_complete=True
    )


def test_missing_configmap_abstains_on_unmounted_or_incomplete_projection() -> None:
    unmounted = deepcopy(_resources())
    unmounted[0]["pod_template"]["containers"][0]["volume_mounts"] = []  # type: ignore[index]
    incomplete = deepcopy(_resources())
    incomplete[0]["pod_template"]["volume_projection_complete"] = False  # type: ignore[index]
    assert not missing_configmap_mount_findings(
        unmounted, [_receipt("confirmed_absent")], evidence_complete=True
    )
    assert not missing_configmap_mount_findings(
        incomplete, [_receipt("confirmed_absent")], evidence_complete=True
    )


def test_missing_configmap_abstains_on_healthy_or_ambiguous_mounts() -> None:
    healthy = deepcopy(_resources())
    healthy[0]["ready"] = 2
    ambiguous = deepcopy(_resources())
    ambiguous[0]["pod_template"]["volumes"].append(  # type: ignore[index]
        {"name": "other", "configmap_name": "settings"}
    )
    ambiguous[0]["pod_template"]["containers"][0]["volume_mounts"].append(  # type: ignore[index]
        {"name": "other"}
    )
    assert not missing_configmap_mount_findings(
        healthy, [_receipt("confirmed_absent")], evidence_complete=True
    )
    assert not missing_configmap_mount_findings(
        ambiguous, [_receipt("confirmed_absent")], evidence_complete=True
    )


def test_missing_configmap_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = missing_configmap_mount_findings(
        _resources(), [_receipt("confirmed_absent")], evidence_complete=True
    )
    renamed = deepcopy(_resources())
    renamed[0]["namespace"] = "renamed-app"
    receipt = _receipt("confirmed_absent")
    receipt["namespace"] = "renamed-app"
    assert (
        missing_configmap_mount_findings(
            list(reversed(_resources())), [_receipt("confirmed_absent")], evidence_complete=True
        )
        == expected
    )
    assert (
        missing_configmap_mount_findings(renamed, [receipt], evidence_complete=True)[0][
            "configmap"
        ]["namespace"]
        == "renamed-app"
    )


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "desired": 2,
            "ready": 1,
            "pod_template": {
                "projection_complete": True,
                "volume_projection_complete": True,
                "volumes": [{"name": "config", "configmap_name": "settings"}],
                "containers": [
                    {
                        "name": "api",
                        "volume_mount_projection_complete": True,
                        "volume_mounts": [{"name": "config"}],
                    }
                ],
            },
        }
    ]


def _receipt(status: str) -> dict[str, object]:
    return {"namespace": "example-app", "name": "settings", "status": status}
