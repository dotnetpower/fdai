"""Bind one reviewed immutable Forseti historical replay archive."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from fdai.agents import ForsetiHistoricalQualitySample, ForsetiHistoricalReplay
from fdai.delivery.forseti_historical_replay import ImmutableForsetiHistoricalReplaySource

_PATH_ENV = "FDAI_FORSETI_REPLAY_EVIDENCE_PATH"
_DIGEST_ENV = "FDAI_FORSETI_REPLAY_EVIDENCE_SHA256"
_SOURCE_REVISION_ENV = "FDAI_SOURCE_REVISION"
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 4096
_MAX_EVIDENCE_REFS = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def build_forseti_historical_replay_source(
    environment: Mapping[str, str],
) -> ImmutableForsetiHistoricalReplaySource | None:
    """Load one exact reviewed archive or keep historical replay unbound."""

    path_value = environment.get(_PATH_ENV, "").strip()
    expected_digest = environment.get(_DIGEST_ENV, "").strip()
    if not path_value and not expected_digest:
        return None
    if not path_value or not expected_digest:
        raise RuntimeError("Forseti replay evidence configuration is incomplete")
    source_revision = environment.get(_SOURCE_REVISION_ENV, "").strip()
    if not source_revision:
        raise RuntimeError("Forseti replay evidence requires FDAI_SOURCE_REVISION")
    path = Path(path_value)
    if not path.is_absolute():
        raise RuntimeError("Forseti replay evidence path MUST be absolute")
    try:
        replay = _load_replay(
            path,
            expected_digest=expected_digest,
            source_revision=source_revision,
        )
    except ValueError as exc:
        raise RuntimeError("Forseti replay evidence is invalid") from exc
    return ImmutableForsetiHistoricalReplaySource(replay)


def _load_replay(
    path: Path,
    *,
    expected_digest: str,
    source_revision: str,
) -> ForsetiHistoricalReplay:
    if _SHA256.fullmatch(expected_digest) is None:
        raise ValueError("Forseti replay evidence digest MUST be lowercase SHA-256")
    content = _read_bounded_regular_file(path)
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ValueError("Forseti replay evidence digest mismatch")
    raw = _object(_load_unique_json(content), "manifest")
    _exact_fields(
        raw,
        {
            "schema_version",
            "source_revision",
            "archive_ref",
            "review_ref",
            "history_complete",
            "window_started_at",
            "window_ended_at",
            "evidence_refs",
            "records",
        },
        "manifest",
    )
    if raw["schema_version"] != "1.0.0":
        raise ValueError("unsupported Forseti replay evidence schema")
    if _text(raw, "source_revision") != source_revision:
        raise ValueError("Forseti replay evidence source revision differs")
    if _REVISION.fullmatch(source_revision) is None:
        raise ValueError("Forseti replay source revision is invalid")
    if raw["history_complete"] is not True:
        raise ValueError("Forseti replay evidence MUST declare complete bounded history")
    window_started_at, started = _timestamp(raw, "window_started_at")
    window_ended_at, ended = _timestamp(raw, "window_ended_at")
    if ended < started:
        raise ValueError("Forseti replay evidence window is reversed")
    evidence_refs = _references(raw["evidence_refs"], "evidence_refs")
    rows = _object_list(raw["records"], "records")
    if len(rows) > _MAX_RECORDS:
        raise ValueError("Forseti replay evidence exceeds its record bound")
    samples = tuple(
        _sample(
            row,
            window_started_at=started,
            window_ended_at=ended,
            archive_evidence_refs=frozenset(evidence_refs),
        )
        for row in rows
    )
    if len({sample.key for sample in samples}) != len(samples):
        raise ValueError("Forseti replay sample keys MUST be unique")
    observed = tuple(datetime.fromisoformat(sample.observed_at) for sample in samples)
    if observed != tuple(sorted(observed)):
        raise ValueError("Forseti replay samples MUST be ordered oldest first")
    return ForsetiHistoricalReplay(
        archive_ref=_text(raw, "archive_ref"),
        content_digest=expected_digest,
        source_revision=source_revision,
        review_ref=_text(raw, "review_ref"),
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        evidence_refs=evidence_refs,
        samples=samples,
    )


def _sample(
    raw: Mapping[str, object],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
    archive_evidence_refs: frozenset[str],
) -> ForsetiHistoricalQualitySample:
    _exact_fields(
        raw,
        {
            "key",
            "event_type",
            "action_type",
            "risk_verdict",
            "judgment_table_digest",
            "tier",
            "observed_at",
            "evidence_refs",
        },
        "record",
    )
    risk_verdict = _optional_text(raw, "risk_verdict")
    if risk_verdict not in {"", "auto", "hil", "deny"}:
        raise ValueError("Forseti replay risk verdict is invalid")
    tier = _text(raw, "tier")
    if tier not in {"T0", "T1", "T2"}:
        raise ValueError("Forseti replay tier is invalid")
    judgment_table_digest = _optional_text(raw, "judgment_table_digest")
    if judgment_table_digest and (
        not judgment_table_digest.startswith("sha256:")
        or _SHA256.fullmatch(judgment_table_digest[7:]) is None
    ):
        raise ValueError("Forseti replay judgment table digest is invalid")
    observed_at, observed = _timestamp(raw, "observed_at")
    if observed < window_started_at or observed > window_ended_at:
        raise ValueError("Forseti replay sample is outside the declared window")
    evidence_refs = _references(raw["evidence_refs"], "record evidence_refs")
    if not frozenset(evidence_refs).issubset(archive_evidence_refs):
        raise ValueError("Forseti replay sample evidence is absent from the archive manifest")
    return ForsetiHistoricalQualitySample(
        key=_text(raw, "key"),
        event_type=_text(raw, "event_type"),
        action_type=_optional_text(raw, "action_type"),
        risk_verdict=risk_verdict,
        judgment_table_digest=judgment_table_digest,
        tier=tier,
        observed_at=observed_at,
        evidence_refs=evidence_refs,
    )


def _load_unique_json(content: bytes) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Forseti replay evidence contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Forseti replay evidence is not valid UTF-8 JSON") from exc


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Forseti replay evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise ValueError("Forseti replay evidence file is invalid or oversized")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(_MAX_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("Forseti replay evidence file is invalid or oversized")
    return content


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Forseti replay {label} MUST be an object")
    return value


def _object_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"Forseti replay {label} MUST be an array")
    return tuple(_object(item, label) for item in value)


def _exact_fields(raw: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"Forseti replay {label} fields are incomplete or unknown")


def _text(raw: Mapping[str, object], field: str) -> str:
    value = _optional_text(raw, field)
    if not value:
        raise ValueError(f"Forseti replay {field} MUST be non-empty")
    return value


def _optional_text(raw: Mapping[str, object], field: str) -> str:
    value = raw.get(field)
    if (
        not isinstance(value, str)
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"Forseti replay {field} MUST be canonical text")
    return value


def _references(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > _MAX_EVIDENCE_REFS:
        raise ValueError(f"Forseti replay {label} MUST be a bounded non-empty array")
    references = tuple(_canonical_reference(item, label) for item in value)
    if len(set(references)) != len(references):
        raise ValueError(f"Forseti replay {label} MUST be unique")
    return references


def _canonical_reference(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Forseti replay {label} MUST contain text references")
    return _text({label: value}, label)


def _timestamp(raw: Mapping[str, object], field: str) -> tuple[str, datetime]:
    value = _text(raw, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Forseti replay {field} MUST be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Forseti replay {field} MUST be timezone-aware")
    return value, parsed


__all__ = ["build_forseti_historical_replay_source"]
