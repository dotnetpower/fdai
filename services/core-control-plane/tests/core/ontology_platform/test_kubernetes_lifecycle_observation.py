"""Kubernetes lifecycle observation model and reason normalization tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KUBERNETES_LIFECYCLE_BACKOFF,
    KUBERNETES_LIFECYCLE_DELETION,
    KUBERNETES_LIFECYCLE_FAILED,
    KUBERNETES_LIFECYCLE_KILLING,
    KUBERNETES_LIFECYCLE_OTHER,
    KUBERNETES_LIFECYCLE_SCHEDULED,
    KUBERNETES_LIFECYCLE_STARTED,
    KUBERNETES_LIFECYCLE_SUCCESSFUL_CREATE,
    KUBERNETES_LIFECYCLE_UNHEALTHY,
    KubernetesLifecycleObservation,
    normalize_kubernetes_lifecycle_reason,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _observation(**overrides: object) -> KubernetesLifecycleObservation:
    fields: dict[str, object] = {
        "cluster_ref": "cluster-a",
        "namespace": "example-namespace",
        "object_uid": "pod-uid-a",
        "owner_uid": "replicaset-uid-a",
        "reason": "Killing",
        "category": KUBERNETES_LIFECYCLE_KILLING,
        "event_type": "Normal",
        "event_time": NOW,
        "recorded_time": NOW,
        "source_revision": "1001",
        "evidence_ref": "kubernetes-lifecycle:" + "a" * 64,
    }
    fields.update(overrides)
    return KubernetesLifecycleObservation(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("Killing", KUBERNETES_LIFECYCLE_KILLING),
        ("Failed", KUBERNETES_LIFECYCLE_FAILED),
        ("BackOff", KUBERNETES_LIFECYCLE_BACKOFF),
        ("Backoff", KUBERNETES_LIFECYCLE_BACKOFF),
        ("Unhealthy", KUBERNETES_LIFECYCLE_UNHEALTHY),
        ("SuccessfulCreate", KUBERNETES_LIFECYCLE_SUCCESSFUL_CREATE),
        ("Scheduled", KUBERNETES_LIFECYCLE_SCHEDULED),
        ("Started", KUBERNETES_LIFECYCLE_STARTED),
        ("SuccessfulDelete", KUBERNETES_LIFECYCLE_DELETION),
        ("FailedDelete", KUBERNETES_LIFECYCLE_DELETION),
        ("Deleted", KUBERNETES_LIFECYCLE_DELETION),
        ("Pulled", KUBERNETES_LIFECYCLE_OTHER),
        ("", KUBERNETES_LIFECYCLE_OTHER),
    ],
)
def test_normalize_reason_uses_only_the_reason_token(reason: str, expected: str) -> None:
    assert normalize_kubernetes_lifecycle_reason(reason) == expected


def test_normalize_reason_never_consults_message_text() -> None:
    # A message that reads like "Killing" MUST NOT influence the category; only the
    # `reason` token (a distinct, structured field) may participate in identity.
    assert normalize_kubernetes_lifecycle_reason("Started") == KUBERNETES_LIFECYCLE_STARTED


def test_observation_accepts_a_well_formed_record() -> None:
    observation = _observation()
    assert observation.category == KUBERNETES_LIFECYCLE_KILLING
    assert observation.owner_uid == "replicaset-uid-a"


def test_observation_allows_absent_owner_and_namespace() -> None:
    observation = _observation(namespace=None, owner_uid=None)
    assert observation.namespace is None
    assert observation.owner_uid is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"cluster_ref": ""},
        {"object_uid": ""},
        {"reason": ""},
        {"event_type": ""},
        {"source_revision": ""},
        {"evidence_ref": ""},
        {"namespace": ""},
        {"owner_uid": ""},
        {"category": "unknown-category"},
    ],
)
def test_observation_rejects_blank_or_unrecognized_fields(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Kubernetes lifecycle"):
        _observation(**overrides)


def test_observation_requires_timezone_aware_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(event_time=datetime(2026, 8, 27, 12, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(recorded_time=datetime(2026, 8, 27, 12, 0))
