"""ReadWriteOnce placement conflict candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.rwo import rwo_anti_affinity_findings


def test_rwo_conflict_requires_complete_mounted_claim_and_required_affinity() -> None:
    finding = rwo_anti_affinity_findings(_resources(), evidence_complete=True)[0]

    assert finding["reason"] == "workload_rwo_claim_anti_affinity_conflict_candidate"
    assert finding["claim"] == {"name": "data", "access_mode": "ReadWriteOnce"}
    assert finding["decision"] == "hold"


def test_rwo_conflict_abstains_on_truncated_or_rwx_evidence() -> None:
    rwx = deepcopy(_resources())
    rwx[0]["access_modes"] = ["ReadWriteMany"]
    assert not rwo_anti_affinity_findings(_resources(), evidence_complete=False)
    assert not rwo_anti_affinity_findings(rwx, evidence_complete=True)


def test_rwo_conflict_abstains_on_unmounted_or_incomplete_projection() -> None:
    unmounted = deepcopy(_resources())
    unmounted[1]["pod_template"]["containers"][0]["volume_mounts"] = []  # type: ignore[index]
    incomplete = deepcopy(_resources())
    incomplete[1]["pod_template"]["volume_projection_complete"] = False  # type: ignore[index]
    assert not rwo_anti_affinity_findings(unmounted, evidence_complete=True)
    assert not rwo_anti_affinity_findings(incomplete, evidence_complete=True)


def test_rwo_conflict_abstains_on_selector_mismatch_or_single_replica() -> None:
    mismatch = deepcopy(_resources())
    mismatch[1]["pod_template"]["labels"] = {"app": "other"}  # type: ignore[index]
    single = deepcopy(_resources())
    single[1]["desired"] = 1
    assert not rwo_anti_affinity_findings(mismatch, evidence_complete=True)
    assert not rwo_anti_affinity_findings(single, evidence_complete=True)


def test_rwo_conflict_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = rwo_anti_affinity_findings(_resources(), evidence_complete=True)
    renamed = deepcopy(_resources())
    for resource in renamed:
        resource["namespace"] = "renamed-app"
    assert (
        rwo_anti_affinity_findings(list(reversed(_resources())), evidence_complete=True) == expected
    )
    assert (
        rwo_anti_affinity_findings(renamed, evidence_complete=True)[0]["resource"]["namespace"]
        == "renamed-app"
    )


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "PersistentVolumeClaim",
            "namespace": "example-app",
            "name": "data",
            "projection_complete": True,
            "access_modes": ["ReadWriteOnce"],
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "desired": 2,
            "ready": 1,
            "pod_template": {
                "projection_complete": True,
                "volume_projection_complete": True,
                "anti_affinity_projection_complete": True,
                "labels": {"app": "api"},
                "required_pod_anti_affinity": [
                    {
                        "topology_key": "kubernetes.io/hostname",
                        "selector_match_labels": {"app": "api"},
                    }
                ],
                "volumes": [{"name": "storage", "claim_name": "data"}],
                "containers": [
                    {
                        "name": "api",
                        "volume_mount_projection_complete": True,
                        "volume_mounts": [{"name": "storage"}],
                    }
                ],
            },
        },
    ]
