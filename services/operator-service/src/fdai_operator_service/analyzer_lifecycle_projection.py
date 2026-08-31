"""Project bounded analyzer receipts into current and historical lifecycle state."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai_operator_service.families.operations import ProjectionUnavailableError

_EVIDENCE_STATES = frozenset({"complete", "incomplete", "conflicting", "missed"})
_PUBLICATION_STATES = frozenset(
    {
        "published",
        "published_receipt_unrecorded",
        "duplicate_suppressed",
        "failed",
    }
)
_MAX_RECEIPTS = 500


def project_analyzer_lifecycle(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Separate each target's newest assessment from its retained history."""
    if len(rows) > _MAX_RECEIPTS:
        raise ProjectionUnavailableError("analyzer lifecycle receipt bound was exceeded")
    receipts = [
        _decode_receipt(row.get("value"), newest_rank=index) for index, row in enumerate(rows)
    ]
    by_assessment: dict[str, list[dict[str, object]]] = defaultdict(list)
    for receipt in receipts:
        by_assessment[str(receipt["idempotency_key"])].append(receipt)

    assessments = [_assessment(items) for items in by_assessment.values()]
    by_resource: dict[str, list[dict[str, object]]] = defaultdict(list)
    for assessment in assessments:
        by_resource[str(assessment["resource_ref"])].append(assessment)

    targets: list[dict[str, object]] = []
    for resource_ref, resource_assessments in sorted(by_resource.items()):
        ordered = sorted(
            resource_assessments,
            key=lambda item: (str(item["occurred_at"]), str(item["idempotency_key"])),
            reverse=True,
        )
        targets.append(
            {
                "resource_ref": resource_ref,
                "current": ordered[0],
                "history": ordered[1:],
            }
        )

    evidence_counts = Counter(str(item["evidence_state"]) for item in assessments)
    observed_at = max(
        (str(receipt["recorded_at"]) for receipt in receipts),
        default=None,
    )
    return {
        "source": "postgresql:state_kv:analyzer-finding-receipt",
        "observed_at": observed_at,
        "target_count": len(targets),
        "assessment_count": len(assessments),
        "evidence_counts": {
            state: evidence_counts.get(state, 0)
            for state in ("complete", "incomplete", "conflicting", "missed")
        },
        "targets": targets,
    }


def _assessment(receipts: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(receipts, key=_newest_rank, reverse=True)
    newest = ordered[-1]
    for receipt in ordered[:-1]:
        for field in (
            "resource_ref",
            "resource_kind",
            "signal",
            "occurred_at",
            "current_state",
            "evidence_complete",
            "evidence_state",
            "recovery_closed",
            "evidence_refs",
        ):
            if receipt[field] != newest[field]:
                raise ProjectionUnavailableError(
                    "analyzer lifecycle receipt identity is conflicting"
                )
    publications = list(dict.fromkeys(str(item["publication"]) for item in ordered))
    recovery_closed = newest["recovery_closed"]
    recovery_state = (
        "verified" if recovery_closed is True else "open" if recovery_closed is False else "unknown"
    )
    return {
        "idempotency_key": newest["idempotency_key"],
        "resource_ref": newest["resource_ref"],
        "resource_kind": newest["resource_kind"],
        "signal": newest["signal"],
        "occurred_at": newest["occurred_at"],
        "recorded_at": newest["recorded_at"],
        "current_state": newest["current_state"],
        "detection_latency_seconds": newest["detection_latency_seconds"],
        "evidence_complete": newest["evidence_complete"],
        "evidence_state": newest["evidence_state"],
        "publication": {
            "current": publications[-1],
            "attempts": publications,
            "duplicate_observed": "duplicate_suppressed" in publications,
        },
        "recovery_state": recovery_state,
        "evidence_refs": newest["evidence_refs"],
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def _newest_rank(receipt: Mapping[str, object]) -> int:
    value = receipt.get("_newest_rank")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionUnavailableError("analyzer lifecycle receipt ordering is malformed")
    return value


def _decode_receipt(value: object, *, newest_rank: int) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError("analyzer lifecycle receipt is malformed")
    receipt = dict(value)
    if receipt.get("schema_version") != "1.0.0":
        raise ProjectionUnavailableError("analyzer lifecycle receipt version is unsupported")
    evidence_state = _required_member(receipt, "evidence_state", _EVIDENCE_STATES)
    publication = _required_member(receipt, "publication", _PUBLICATION_STATES)
    evidence_refs = receipt.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or len(evidence_refs) > 128
        or any(not isinstance(item, str) or not item or len(item) > 512 for item in evidence_refs)
        or len(evidence_refs) != len(set(evidence_refs))
    ):
        raise ProjectionUnavailableError("analyzer lifecycle evidence references are malformed")
    recovery_closed = receipt.get("recovery_closed")
    if recovery_closed is not None and not isinstance(recovery_closed, bool):
        raise ProjectionUnavailableError("analyzer lifecycle recovery state is malformed")
    evidence_complete = receipt.get("evidence_complete")
    if not isinstance(evidence_complete, bool):
        raise ProjectionUnavailableError("analyzer lifecycle completeness is malformed")
    if evidence_complete != (evidence_state == "complete"):
        raise ProjectionUnavailableError("analyzer lifecycle completeness is inconsistent")
    latency = receipt.get("detection_latency_seconds")
    if not isinstance(latency, (int, float)) or isinstance(latency, bool) or latency < 0:
        raise ProjectionUnavailableError("analyzer lifecycle latency is malformed")
    if receipt.get("cause_claim_supported") is not False:
        raise ProjectionUnavailableError("analyzer lifecycle cause boundary is malformed")
    if receipt.get("execution_authority") is not False:
        raise ProjectionUnavailableError("analyzer lifecycle authority boundary is malformed")
    return {
        "idempotency_key": _required_text(receipt, "idempotency_key", 1024),
        "resource_ref": _required_text(receipt, "resource_ref", 512),
        "resource_kind": _required_text(receipt, "resource_kind", 128),
        "signal": _required_text(receipt, "signal", 128),
        "occurred_at": _required_timestamp(receipt, "occurred_at"),
        "recorded_at": _required_timestamp(receipt, "recorded_at"),
        "current_state": _required_text(receipt, "current_state", 128),
        "detection_latency_seconds": float(latency),
        "evidence_complete": evidence_complete,
        "evidence_state": evidence_state,
        "publication": publication,
        "recovery_closed": recovery_closed,
        "evidence_refs": evidence_refs,
        "_newest_rank": newest_rank,
    }


def _required_text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item) > maximum:
        raise ProjectionUnavailableError(f"analyzer lifecycle {key} is malformed")
    return item


def _required_member(
    value: Mapping[str, Any],
    key: str,
    allowed: frozenset[str],
) -> str:
    item = _required_text(value, key, 128)
    if item not in allowed:
        raise ProjectionUnavailableError(f"analyzer lifecycle {key} is unsupported")
    return item


def _required_timestamp(value: Mapping[str, Any], key: str) -> str:
    item = _required_text(value, key, 64)
    try:
        parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionUnavailableError(f"analyzer lifecycle {key} is malformed") from exc
    if parsed.tzinfo is None:
        raise ProjectionUnavailableError(f"analyzer lifecycle {key} has no timezone")
    return item


__all__ = ["project_analyzer_lifecycle"]
