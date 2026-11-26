"""Stewardship-change notification builder tests."""

from __future__ import annotations

from fdai.core.stewardship import (
    StewardshipChangeEvent,
    StewardshipChangePhase,
    build_change_audit_payload,
    build_change_notification,
    load_stewardship_from_mapping,
)
from fdai.core.stewardship.notify import CHANGE_CATEGORY
from fdai.shared.providers.notifications.base import TrustTier


def _event() -> StewardshipChangeEvent:
    return StewardshipChangeEvent(
        actor_oid="00000000-0000-0000-0000-000000000009",
        artifact="config/agent-stewardship.yaml",
        affected_agents=("Thor", "Njord"),
        summary="Reassign Thor steward.",
        correlation_id="corr-1",
    )


def test_notification_targets_stewards_and_maintainers(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    message, recipients = build_change_notification(mp, _event())

    assert message.category == CHANGE_CATEGORY
    assert message.trust_tier is TrustTier.A2_OPERATIONAL_ALERT
    assert message.correlation_id == "corr-1"
    # Recipients include the affected agents' stewards + maintainers.
    ids = {r.id for r in recipients}
    assert mp.maintainer_oids[0] in ids
    # steward_oids metadata is populated and de-duplicated.
    meta_ids = message.metadata["steward_oids"].split(",")
    assert len(meta_ids) == len(set(meta_ids))
    assert message.metadata["artifact"] == "config/agent-stewardship.yaml"


def test_notification_body_names_actor_and_agents(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    message, _ = build_change_notification(mp, _event())
    assert "Thor, Njord" in message.body_markdown
    assert "00000000-0000-0000-0000-000000000009" in message.body_markdown


def test_audit_payload_is_l0_and_complete() -> None:
    payload = build_change_audit_payload(_event())
    assert payload["event"] == "stewardship_change_requested"
    assert payload["artifact"] == "config/agent-stewardship.yaml"
    assert payload["affected_agents"] == "Thor,Njord"
    assert payload["correlation_id"] == "corr-1"
    assert "recorded_at" in payload


def test_merged_event_uses_distinct_notification_and_audit_phase(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    event = StewardshipChangeEvent(
        actor_oid="github:user",
        artifact="config/agent-stewardship.yaml",
        affected_agents=("Thor",),
        summary="Governance PR merged.",
        correlation_id="delivery-1",
        phase=StewardshipChangePhase.MERGED,
    )
    message, _ = build_change_notification(mp, event)
    payload = build_change_audit_payload(event)

    assert "merged" in message.title
    assert payload["event"] == "stewardship_change_merged"


def test_no_affected_agents_still_notifies_maintainers(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    event = StewardshipChangeEvent(
        actor_oid="00000000-0000-0000-0000-000000000009",
        artifact="config/notifications-matrix.yaml",
        affected_agents=(),
        summary="Tune fallback order.",
        correlation_id="corr-2",
    )
    message, recipients = build_change_notification(mp, event)
    ids = {r.id for r in recipients}
    # Maintainers are always in the loop even with no agent-specific stewards.
    assert set(mp.maintainer_oids).issubset(ids)
    assert "(none)" in message.body_markdown
