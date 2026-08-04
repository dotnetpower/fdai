"""Bounded Kubernetes log target selection tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.log_targets import select_bounded_log_targets


def test_log_targets_prioritize_active_failure_and_reserve_recent_capacity() -> None:
    resources = [
        _pod("old-failure", minute=0, state="waiting", ready=False),
        *[_pod(f"noise-{index}", minute=index + 1, ready=False) for index in range(8)],
        _pod("new-ready", minute=59, ready=True),
    ]

    targets = select_bounded_log_targets(
        resources,
        evidence_complete=True,
        max_pods=4,
        max_containers_per_pod=2,
    )

    assert targets[0]["name"] == "old-failure"
    assert "active_failure" in targets[0]["selection_reasons"]
    assert any(target["name"] == "new-ready" for target in targets)
    assert len(targets) == 4


def test_log_targets_prioritize_failing_container_inside_pod() -> None:
    pod = _pod("api", minute=1, ready=False)
    pod["containers"] = [
        _status("app", ready=False),
        _status("sidecar", state="waiting", ready=False),
    ]

    targets = select_bounded_log_targets(
        [pod], evidence_complete=True, max_pods=1, max_containers_per_pod=1
    )

    assert targets[0]["containers"] == ["sidecar"]


def test_log_targets_abstain_on_truncated_or_malformed_evidence() -> None:
    malformed = _pod("api", minute=1)
    malformed["created_at"] = "not-a-time"

    assert not select_bounded_log_targets(
        [_pod("api", minute=1)],
        evidence_complete=False,
        max_pods=1,
        max_containers_per_pod=1,
    )
    assert not select_bounded_log_targets(
        [malformed],
        evidence_complete=True,
        max_pods=1,
        max_containers_per_pod=1,
    )


def test_log_targets_reject_ambiguous_uid_or_incomplete_container_projection() -> None:
    duplicate = _pod("api", minute=1)
    incomplete = _pod("other", minute=2)
    incomplete["container_status_projection_complete"] = False

    assert not select_bounded_log_targets(
        [duplicate, deepcopy(duplicate), incomplete],
        evidence_complete=True,
        max_pods=2,
        max_containers_per_pod=1,
    )


def test_log_targets_are_metamorphic_to_input_order_and_identity_rename() -> None:
    resources = [_pod("old", minute=1, ready=False), _pod("new", minute=59, ready=True)]
    expected = select_bounded_log_targets(
        resources, evidence_complete=True, max_pods=2, max_containers_per_pod=1
    )
    renamed = deepcopy(resources)
    for resource in renamed:
        resource["namespace"] = "renamed-app"

    assert (
        select_bounded_log_targets(
            list(reversed(resources)),
            evidence_complete=True,
            max_pods=2,
            max_containers_per_pod=1,
        )
        == expected
    )
    renamed_targets = select_bounded_log_targets(
        renamed, evidence_complete=True, max_pods=2, max_containers_per_pod=1
    )
    assert all(target["namespace"] == "renamed-app" for target in renamed_targets)


def _pod(
    name: str,
    *,
    minute: int,
    state: str = "running",
    ready: bool = True,
) -> dict[str, object]:
    return {
        "kind": "Pod",
        "namespace": "example-app",
        "name": name,
        "uid": f"{name}-uid",
        "created_at": f"2026-08-04T11:{minute:02d}:00Z",
        "container_status_projection_complete": True,
        "containers": [_status("app", state=state, ready=ready)],
    }


def _status(name: str, *, state: str = "running", ready: bool = True) -> dict[str, object]:
    return {
        "name": name,
        "ready": ready,
        "restarts": 0,
        "state": state,
        "reason": "CrashLoopBackOff" if state == "waiting" else "",
    }
