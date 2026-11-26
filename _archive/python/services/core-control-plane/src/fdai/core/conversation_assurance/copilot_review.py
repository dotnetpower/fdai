"""Digest-bound import contract for operator-triggered GitHub Copilot reviews."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, TypedDict

from .pantheon_ledger import PrivateJsonlLedger, write_private_text_exclusive

COPILOT_REVIEWER_KIND: Final = "github_copilot_session"
COPILOT_RUBRIC_NAMES: Final[tuple[str, ...]] = (
    "appropriateness",
    "completeness",
    "grounding",
    "verification",
    "authority_safety",
    "visualization",
    "investigation_detail",
    "execution_detail",
    "performance",
    "response_integrity",
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_MAX_PACKET_BYTES: Final = 4 * 1024 * 1024
_MAX_CASE_BYTES: Final = 256 * 1024
_MAX_CASES: Final = 100


class _Rubric(TypedDict):
    name: str
    score: int | None
    reason: str


def build_copilot_review_packet(
    cases: Sequence[Mapping[str, object]],
    *,
    created_at: str,
) -> dict[str, object]:
    """Build a review packet whose cases and complete body are digest-bound."""

    _timestamp(created_at, "packet created_at")
    if not 1 <= len(cases) <= _MAX_CASES:
        raise ValueError("Copilot review packet case count MUST be in [1, 100]")
    normalized_cases = tuple(_review_case(value) for value in cases)
    body: dict[str, object] = {
        "schema_version": "1.0.0",
        "created_at": created_at,
        "reviewer_kind": COPILOT_REVIEWER_KIND,
        "cases": list(normalized_cases),
        "qualification_authority": False,
        "execution_authority": False,
    }
    packet_digest = _content_digest(body)
    packet = {
        **body,
        "packet_id": f"copilot-review:{packet_digest[:24]}",
        "packet_digest": packet_digest,
    }
    _bounded_json(packet, _MAX_PACKET_BYTES, "Copilot review packet")
    return packet


def validate_copilot_review_packet(raw: Mapping[str, object]) -> dict[str, object]:
    """Validate an exported packet and return its canonical representation."""

    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Copilot review packet cases MUST be a list")
    created_at = raw.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("Copilot review packet created_at MUST be a string")
    canonical = build_copilot_review_packet(cases, created_at=created_at)
    for field in (
        "schema_version",
        "reviewer_kind",
        "qualification_authority",
        "execution_authority",
        "packet_digest",
        "packet_id",
    ):
        if raw.get(field) != canonical[field]:
            raise ValueError(f"Copilot review packet {field} is invalid")
    if set(raw) != set(canonical):
        raise ValueError("Copilot review packet contains unsupported fields")
    return canonical


def write_copilot_review_packet(path: Path, packet: Mapping[str, object]) -> None:
    """Write one validated packet to a new owner-only file."""

    canonical = validate_copilot_review_packet(packet)
    content = json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_private_text_exclusive(path, content, max_bytes=_MAX_PACKET_BYTES)


def import_copilot_review(
    *,
    packet: Mapping[str, object],
    result: Mapping[str, object],
    ledger: PrivateJsonlLedger,
) -> dict[str, object]:
    """Validate one Copilot-authored result and append it without granting authority."""

    canonical_packet = validate_copilot_review_packet(packet)
    record = _review_record(canonical_packet, result)
    prior = ledger.read(limit=10_000)
    if any(item.get("review_id") == record["review_id"] for item in prior):
        return {**record, "duplicate": True}
    ledger.append(record)
    return {**record, "duplicate": False}


def _review_case(raw: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("Copilot review case MUST be an object")
    case_id = _token(raw.get("case_id"), "case_id")
    question = _bounded_text(raw.get("question"), "question")
    answer = _bounded_text(raw.get("answer"), "answer")
    evidence = raw.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("Copilot review case evidence MUST be an object")
    body: dict[str, object] = {
        "case_id": case_id,
        "question": question,
        "answer": answer,
        "evidence": {str(key): value for key, value in evidence.items()},
    }
    _bounded_json(body, _MAX_CASE_BYTES, "Copilot review case")
    return {**body, "case_digest": _content_digest(body)}


def _review_record(
    packet: Mapping[str, object],
    result: Mapping[str, object],
) -> dict[str, object]:
    reviewed_at = result.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise ValueError("Copilot review result reviewed_at MUST be a string")
    _timestamp(reviewed_at, "reviewed_at")
    for field, expected in (
        ("schema_version", "1.0.0"),
        ("reviewer_kind", COPILOT_REVIEWER_KIND),
        ("packet_digest", packet["packet_digest"]),
        ("qualification_authority", False),
        ("execution_authority", False),
    ):
        if result.get(field) != expected:
            raise ValueError(f"Copilot review result {field} is invalid")
    reviews = result.get("reviews")
    packet_cases = packet["cases"]
    if not isinstance(reviews, list) or not isinstance(packet_cases, list):
        raise ValueError("Copilot review result reviews MUST be a list")
    expected_cases = {
        value["case_id"]: value for value in packet_cases if isinstance(value, Mapping)
    }
    normalized = tuple(_case_review(value, expected_cases) for value in reviews)
    if tuple(value["case_id"] for value in normalized) != tuple(expected_cases):
        raise ValueError("Copilot review result MUST cover packet cases in order")
    body: dict[str, object] = {
        "schema_version": "1.0.0",
        "event": "copilot_review_imported",
        "packet_id": packet["packet_id"],
        "packet_digest": packet["packet_digest"],
        "reviewer_kind": COPILOT_REVIEWER_KIND,
        "reviewed_at": reviewed_at,
        "reviews": list(normalized),
        "qualification_authority": False,
        "execution_authority": False,
    }
    review_id = f"copilot-result:{_content_digest(body)}"
    return {**body, "review_id": review_id}


def _case_review(
    raw: object,
    expected_cases: Mapping[object, Mapping[str, object]],
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("Copilot case review MUST be an object")
    case_id = _token(raw.get("case_id"), "review case_id")
    expected = expected_cases.get(case_id)
    if expected is None or raw.get("case_digest") != expected.get("case_digest"):
        raise ValueError("Copilot case review digest does not match its packet")
    rubrics = raw.get("rubrics")
    if not isinstance(rubrics, list):
        raise ValueError("Copilot case review rubrics MUST be a list")
    normalized_rubrics = tuple(_rubric(value) for value in rubrics)
    if tuple(value["name"] for value in normalized_rubrics) != COPILOT_RUBRIC_NAMES:
        raise ValueError("Copilot case review rubrics MUST use canonical order")
    score = sum(value["score"] or 0 for value in normalized_rubrics)
    maximum = sum(value["score"] is not None for value in normalized_rubrics)
    mandatory = {
        "appropriateness",
        "completeness",
        "grounding",
        "verification",
        "authority_safety",
        "response_integrity",
    }
    mandatory_failures = [
        value["name"]
        for value in normalized_rubrics
        if value["name"] in mandatory and value["score"] != 1
    ]
    return {
        "case_id": case_id,
        "case_digest": expected["case_digest"],
        "rubrics": list(normalized_rubrics),
        "total_score": score,
        "max_score": maximum,
        "mandatory_gate_failures": mandatory_failures,
        "assurance_passed": not mandatory_failures and maximum > 0 and score / maximum >= 0.9,
    }


def _rubric(raw: object) -> _Rubric:
    if not isinstance(raw, Mapping):
        raise ValueError("Copilot review rubric MUST be an object")
    name = raw.get("name")
    score = raw.get("score")
    reason = raw.get("reason")
    if name not in COPILOT_RUBRIC_NAMES:
        raise ValueError("Copilot review rubric name is invalid")
    if score not in {0, 1, None} or isinstance(score, bool):
        raise ValueError("Copilot review rubric score MUST be 0, 1, or null")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValueError("Copilot review rubric reason MUST be bounded")
    return {"name": name, "score": score, "reason": reason}


def _bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 64 * 1024:
        raise ValueError(f"Copilot review case {label} MUST be bounded")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"Copilot review {label} MUST be a portable token")
    return value


def _timestamp(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Copilot review {label} MUST be RFC 3339") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Copilot review {label} MUST be timezone-aware")


def _bounded_json(value: object, limit: int, label: str) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        raise ValueError(f"{label} MUST contain JSON-compatible values") from None
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds the byte limit")
    return payload


def _content_digest(value: object) -> str:
    payload = _bounded_json(value, _MAX_PACKET_BYTES, "Copilot review content")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "COPILOT_REVIEWER_KIND",
    "COPILOT_RUBRIC_NAMES",
    "build_copilot_review_packet",
    "import_copilot_review",
    "validate_copilot_review_packet",
    "write_copilot_review_packet",
]
