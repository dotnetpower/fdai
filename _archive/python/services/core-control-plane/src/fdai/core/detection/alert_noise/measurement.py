"""Distinct episode, attempt, channel delivery and human-acknowledgement denominators."""

from __future__ import annotations

from fdai_service_contracts.alert_noise import AlertDelivery


def notification_counts(
    rows: tuple[AlertDelivery, ...],
    *,
    complete: bool,
) -> tuple[int | None, int | None, int | None]:
    """Count each lifecycle identity once; absent identity/completeness stays unknown."""
    if not complete:
        return None, None, None
    notifications = tuple(row for row in rows if row.state != "source")
    identities_complete = all(row.attempt_ref is not None for row in notifications)
    attempts = {row.attempt_ref for row in notifications}
    delivered = {
        row.attempt_ref for row in notifications if row.state in {"delivered", "acknowledged"}
    }
    acknowledgements = tuple(row for row in notifications if row.state == "acknowledged")
    humans_complete = all(row.acknowledger_ref is not None for row in acknowledgements)
    humans = {
        (row.rule_ref, row.episode_ref, row.condition, row.acknowledger_ref)
        for row in acknowledgements
    }
    return (
        len(attempts) if identities_complete else None,
        len(delivered) if identities_complete else None,
        len(humans) if humans_complete else None,
    )


def flapping_transitions(rows: tuple[AlertDelivery, ...]) -> int:
    """Count state alternations, not independent fired episodes or notification updates."""
    source = {(row.event_at, row.condition) for row in rows if row.state == "source"}
    instants = {at for at, _ in source}
    if len(instants) != len(source):
        return 0  # Simultaneous conflicting states do not prove a transition order.
    ordered = [condition for _, condition in sorted(source)]
    return sum(left != right for left, right in zip(ordered, ordered[1:], strict=False))
