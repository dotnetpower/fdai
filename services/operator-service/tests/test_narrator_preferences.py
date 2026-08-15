"""Narrator preferences stay revisioned, principal-scoped, and sanitized."""

from __future__ import annotations

import json

import pytest
from fdai_operator_service.adapters.narrator_latency import NarratorLatencyStats
from fdai_operator_service.adapters.narrator_preferences import (
    AUTO_DEPLOYMENT,
    InMemoryNarratorPreferenceStore,
    NarratorPreferenceConflictError,
    NarratorPreferenceError,
    project_narrator_settings,
)

_ALLOWLIST = ("narrator-primary", "narrator-secondary")


def _stats(deployment: str) -> NarratorLatencyStats:
    return NarratorLatencyStats(
        deployment=deployment,
        sample_count=4,
        latency_p50_ms=820.0,
        latency_p95_ms=1400.0,
        ttft_p50_ms=210.0,
        ttft_p95_ms=430.0,
    )


def test_unset_principal_starts_on_auto_at_revision_zero() -> None:
    store = InMemoryNarratorPreferenceStore()

    preference = store.read("principal-a")

    assert preference.is_auto
    assert preference.revision == 0


def test_creation_uses_revision_zero_and_increments() -> None:
    store = InMemoryNarratorPreferenceStore()

    created = store.write(
        "principal-a",
        deployment="narrator-secondary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    assert created.revision == 1
    assert store.read("principal-a").deployment == "narrator-secondary"


def test_stale_revision_conflicts_instead_of_overwriting() -> None:
    store = InMemoryNarratorPreferenceStore()
    store.write(
        "principal-a",
        deployment="narrator-secondary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    with pytest.raises(NarratorPreferenceConflictError):
        store.write(
            "principal-a",
            deployment="narrator-primary",
            expected_revision=0,
            allowlist=_ALLOWLIST,
        )

    assert store.read("principal-a").deployment == "narrator-secondary"


def test_arbitrary_model_ids_are_rejected() -> None:
    store = InMemoryNarratorPreferenceStore()

    with pytest.raises(NarratorPreferenceError, match="allowlisted"):
        store.write(
            "principal-a",
            deployment="unlisted-deployment",
            expected_revision=0,
            allowlist=_ALLOWLIST,
        )

    assert store.read("principal-a").is_auto


def test_auto_is_always_selectable() -> None:
    store = InMemoryNarratorPreferenceStore()
    store.write(
        "principal-a",
        deployment="narrator-primary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    reset = store.write(
        "principal-a",
        deployment=AUTO_DEPLOYMENT,
        expected_revision=1,
        allowlist=(),
    )

    assert reset.is_auto
    assert reset.revision == 2


def test_preferences_are_isolated_per_principal() -> None:
    store = InMemoryNarratorPreferenceStore()
    store.write(
        "principal-a",
        deployment="narrator-secondary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    other = store.read("principal-b")

    assert other.is_auto
    assert other.revision == 0
    assert other.principal_id == "principal-b"


def test_projection_reports_a_pinned_choice_without_personalizing_t2() -> None:
    store = InMemoryNarratorPreferenceStore()
    preference = store.write(
        "principal-a",
        deployment="narrator-secondary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    projection = project_narrator_settings(
        principal_id="principal-a",
        preference=preference,
        allowlist=_ALLOWLIST,
        latency=(_stats("narrator-primary"), _stats("narrator-secondary")),
    )

    assert projection["mode"] == "pinned"
    assert projection["selected_deployment"] == "narrator-secondary"
    assert projection["applies_to"] == "t1_narrator"
    assert projection["personalizes_t2_bindings"] is False
    assert projection["revision"] == 1


def test_removed_deployment_degrades_to_auto_without_losing_the_stored_choice() -> None:
    store = InMemoryNarratorPreferenceStore()
    preference = store.write(
        "principal-a",
        deployment="narrator-secondary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    projection = project_narrator_settings(
        principal_id="principal-a",
        preference=preference,
        allowlist=("narrator-primary",),
        latency=(_stats("narrator-primary"), _stats("narrator-secondary")),
    )

    assert projection["mode"] == "auto"
    assert projection["selected_deployment"] is None
    assert projection["fallback_reason"] == "deployment_unavailable"
    assert projection["stored_deployment"] == "narrator-secondary"
    assert projection["latency"] == [
        {
            "deployment": "narrator-primary",
            "sample_count": 4,
            "latency_p50_ms": 820.0,
            "latency_p95_ms": 1400.0,
            "ttft_p50_ms": 210.0,
            "ttft_p95_ms": 430.0,
        }
    ]


def test_projection_refuses_another_principals_preference() -> None:
    store = InMemoryNarratorPreferenceStore()
    preference = store.write(
        "principal-a",
        deployment="narrator-primary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    with pytest.raises(NarratorPreferenceError, match="another principal"):
        project_narrator_settings(
            principal_id="principal-b",
            preference=preference,
            allowlist=_ALLOWLIST,
        )


def test_projection_exposes_no_endpoint_or_credential_material() -> None:
    store = InMemoryNarratorPreferenceStore()
    preference = store.write(
        "principal-a",
        deployment="narrator-primary",
        expected_revision=0,
        allowlist=_ALLOWLIST,
    )

    rendered = json.dumps(
        project_narrator_settings(
            principal_id="principal-a",
            preference=preference,
            allowlist=_ALLOWLIST,
            latency=(_stats("narrator-primary"),),
        )
    )

    for forbidden in ("http", "endpoint", "token", "api_key", "audience", "credential"):
        assert forbidden not in rendered.lower()


def test_allowlist_cannot_shadow_the_auto_sentinel() -> None:
    store = InMemoryNarratorPreferenceStore()

    with pytest.raises(NarratorPreferenceError, match="auto sentinel"):
        store.write(
            "principal-a",
            deployment="narrator-primary",
            expected_revision=0,
            allowlist=("narrator-primary", AUTO_DEPLOYMENT),
        )


@pytest.mark.parametrize("principal", ["", "   ", "x" * 129])
def test_principal_bounds_are_enforced(principal: str) -> None:
    store = InMemoryNarratorPreferenceStore()

    with pytest.raises(NarratorPreferenceError, match="principal MUST"):
        store.read(principal)
