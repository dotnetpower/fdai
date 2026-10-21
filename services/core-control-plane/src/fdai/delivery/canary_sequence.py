"""Complete bounded consumption history for one independently observed canary execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.self_health_canary import (
    _timestamp,
    _validated_recorded_at,
    validated_canary_audit,
)
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError

MAX_CANARY_AUDITS = 64


@dataclass(frozen=True, slots=True)
class CanaryConsumption:
    outcome: Literal["success", "failure", "cancelled"]
    observed_at: datetime
    sequence_digest: str

    @property
    def value(self) -> Decimal:
        if self.outcome == "cancelled":
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        return Decimal(int(self.outcome == "success"))


def consumed_canary_sequence(
    rows: tuple[Mapping[str, Any], ...],
    *,
    slot: str,
    truncated: bool,
    now: datetime,
) -> CanaryConsumption:
    """Reject incomplete, conflicting or overlapping retries rather than selecting a success."""
    if now.utcoffset() is None:
        raise ValueError("canary observation requires an aware timestamp")
    if truncated or len(rows) > MAX_CANARY_AUDITS:
        raise SelfHealthExporterUnavailableError(reason="source_incomplete")
    if not rows:
        raise SelfHealthExporterUnavailableError(reason="source_missing")
    try:
        return _project(rows, slot=slot, now=now.astimezone(UTC))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise SelfHealthExporterUnavailableError(reason="source_malformed") from exc


def _project(rows: tuple[Mapping[str, Any], ...], *, slot: str, now: datetime) -> CanaryConsumption:
    if not 1 <= len(slot) <= 100 or slot != slot.strip():
        raise ValueError("canary execution slot is malformed")
    correlation = f"canary:{slot}"
    event_id = str(uuid5(NAMESPACE_URL, f"fdai.canary://{slot}"))
    previous_seq = 0
    previous_time = datetime.min.replace(tzinfo=UTC)
    current_attempt: str | None = None
    current_start: datetime | None = None
    terminal: Literal["success", "failure", "cancelled"] | None = None
    attempts: set[str] = set()
    identities: dict[str, object] | None = None
    lineage: list[dict[str, object]] = []
    for row in rows:
        entry = validated_canary_audit(row)
        if row["seq"] <= previous_seq:
            raise ValueError("canary audit sequence is not strictly increasing")
        if entry["event_id"] != event_id or entry["correlation_id"] != correlation:
            raise ValueError("canary audit does not belong to the observed execution")
        identity = {
            key: entry[key] for key in ("event_id", "correlation_id", "mode", "detected_at")
        }
        if identities is not None and identity != identities:
            raise ValueError("canary retry identity changed")
        identities = identity
        attempt = entry["attempt_id"]
        if not isinstance(attempt, str) or len(attempt) != 36:
            raise ValueError("canary attempt identity is malformed")
        parsed_attempt = UUID(attempt)
        if str(parsed_attempt) != attempt or parsed_attempt.int == 0:
            raise ValueError("canary attempt identity is not canonical")
        started_at = _timestamp(entry["started_at"])
        recorded_at = _timestamp(entry["recorded_at"])
        detected_at = _timestamp(entry["detected_at"])
        if not detected_at <= started_at <= recorded_at:
            raise ValueError("canary attempt time is inconsistent")
        if recorded_at > now:
            raise SelfHealthExporterUnavailableError(reason="source_from_future")
        if recorded_at < previous_time:
            raise ValueError("canary audit clock moved backwards")
        outcome = entry["outcome"]
        if outcome == "started":
            if (
                recorded_at != started_at
                or attempt in attempts
                or current_attempt is not None
                and terminal is None
            ):
                raise ValueError("canary attempt overlaps or replays an earlier attempt")
            attempts.add(attempt)
            current_attempt, current_start, terminal = attempt, started_at, None
        else:
            if attempt != current_attempt or started_at != current_start or terminal is not None:
                raise ValueError("canary terminal lacks its unique preceding start")
            if outcome != "success":
                error_type = entry["error_type"]
                if (
                    not isinstance(error_type, str)
                    or not 1 <= len(error_type) <= 128
                    or not error_type.isascii()
                    or not error_type.isidentifier()
                ):
                    raise ValueError("canary interruption error class is malformed")
            if outcome == "success":
                _validated_recorded_at(row)
                terminal = "success"
            elif outcome == "failure":
                terminal = "failure"
            else:
                terminal = "cancelled"
        lineage.append({"seq": row["seq"], "entry_hash": row["entry_hash"]})
        previous_seq, previous_time = row["seq"], recorded_at
    if terminal is None:
        raise SelfHealthExporterUnavailableError(reason="source_incomplete")
    return CanaryConsumption(
        outcome=terminal,
        observed_at=previous_time,
        sequence_digest=canonical_digest({"slot": slot, "audits": lineage}),
    )
