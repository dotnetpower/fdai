from __future__ import annotations

from datetime import datetime

from fdai_deployment_cli.lifecycle_native_reconciliation import (
    same_transition_state_fields,
    transition_reported_state_digest,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionEntityState,
    NativeScopeTransitionReportedState,
)


def _state(timestamp: str, digest: str) -> NativeScopeTransitionReportedState:
    return NativeScopeTransitionReportedState(
        digest=digest,
        schema_revision=15,
        entities={
            "fdai-workloads": NativeScopeTransitionEntityState(
                release_id=None,
                artifact_digests=(),
                health="unknown",
            )
        },
        observed_at=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
    )


def test_legacy_millisecond_and_hub_microsecond_state_have_distinct_canonical_digests() -> None:
    hub = _state("2026-10-27T00:00:00.787619Z", "0" * 64)
    legacy_digest = transition_reported_state_digest(hub, milliseconds=True)
    authoritative_digest = transition_reported_state_digest(hub)
    local = _state("2026-10-27T00:00:00.787000Z", legacy_digest)
    source = hub.model_copy(update={"digest": legacy_digest})
    authoritative = hub.model_copy(update={"digest": authoritative_digest})

    assert legacy_digest == "a2e334cf8b9ccee724e5dc7cc48424dd6e5de0a4e62130bc44ee9508e1aea15b"
    assert (
        authoritative_digest == "8fd409eca5356406248c1ac6063c0daf8c31da1a1e00291f9d89862fe19ffa47"
    )
    assert same_transition_state_fields(local, source)
    assert same_transition_state_fields(source, authoritative)
    assert source.observed_at - local.observed_at < datetime.resolution * 1000
