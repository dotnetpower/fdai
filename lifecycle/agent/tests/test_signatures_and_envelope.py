from __future__ import annotations

from typing import get_args

from fdai_deployment_cli.lifecycle_plan import CapabilityMode, LifecycleEffectEnvelope

from fdai_lifecycle_agent.inputs import VerifiedRelease


def _envelope(mode: CapabilityMode) -> LifecycleEffectEnvelope:
    return LifecycleEffectEnvelope(
        entity_ids=frozenset({"core"}),
        regions=frozenset({"korea-central"}),
        capability_modes={"action:x": mode},
        destructive_allowed=False,
        max_duration_minutes=30,
    )


def test_declared_mode_order_matches_envelope_narrowing() -> None:
    lower, higher = get_args(CapabilityMode)

    assert _envelope(lower).narrowed_by(_envelope(higher))
    assert not _envelope(higher).narrowed_by(_envelope(lower))


def test_release_lowers_and_drops_capabilities_of_the_local_maximum() -> None:
    release = VerifiedRelease(
        digest="r" * 64, artifact_digests=frozenset(), capability_maximums={"action:x": "shadow"}
    )
    local = _envelope("enforce")
    local = LifecycleEffectEnvelope(
        entity_ids=local.entity_ids,
        regions=local.regions,
        capability_modes={"action:x": "enforce", "action:local-only": "enforce"},
        destructive_allowed=local.destructive_allowed,
        max_duration_minutes=local.max_duration_minutes,
    )

    assert release.maximum_envelope(local).capability_modes == {"action:x": "shadow"}
