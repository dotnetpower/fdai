#!/usr/bin/env python3
"""Append bounded conversational-assurance campaign results to local JSONL."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

_SCHEMA_VERSION: Final = 1
_QID: Final = re.compile(r"^Q[0-9]{3}$")
_COMMIT: Final = re.compile(r"^[0-9a-f]{7,40}$")
_VARIANTS: Final = frozenset({"original", "A", "B", "cohort"})
_MODES: Final = frozenset({"fresh", "positive"})
_STATUSES: Final = frozenset({"verified", "consistent", "corrected", "unverified"})
_MAX_TEXT: Final = 256
_MAX_INPUT_BYTES: Final = 1_000_000
_FIELDS: Final = frozenset(
    {
        "run_id",
        "qid",
        "variant",
        "mode",
        "expected_authority",
        "expected_status",
        "expected_reason",
        "actual_authority",
        "actual_status",
        "actual_reason",
        "checks_completed",
        "checks_total",
        "model_calls",
        "commit",
        "recorded_at",
    }
)


@dataclass(frozen=True, slots=True)
class CampaignResult:
    run_id: str
    qid: str
    variant: str
    mode: str
    expected_authority: str
    expected_status: str
    expected_reason: str | None
    actual_authority: str
    actual_status: str
    actual_reason: str | None
    checks_completed: int
    checks_total: int
    model_calls: int
    commit: str
    recorded_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> CampaignResult:
        unknown = set(raw) - _FIELDS
        missing = _FIELDS - set(raw)
        if unknown or missing:
            raise ValueError("campaign result fields are incomplete or unknown")
        result = cls(
            run_id=_text(raw["run_id"]),
            qid=_text(raw["qid"]),
            variant=_text(raw["variant"]),
            mode=_text(raw["mode"]),
            expected_authority=_text(raw["expected_authority"]),
            expected_status=_text(raw["expected_status"]),
            expected_reason=_optional_text(raw["expected_reason"]),
            actual_authority=_text(raw["actual_authority"]),
            actual_status=_text(raw["actual_status"]),
            actual_reason=_optional_text(raw["actual_reason"]),
            checks_completed=_integer(raw["checks_completed"]),
            checks_total=_integer(raw["checks_total"]),
            model_calls=_integer(raw["model_calls"]),
            commit=_text(raw["commit"]),
            recorded_at=_text(raw["recorded_at"]),
        )
        result._validate()
        return result

    def _validate(self) -> None:
        if _QID.fullmatch(self.qid) is None:
            raise ValueError("qid MUST use Q000 format")
        if self.variant not in _VARIANTS or self.mode not in _MODES:
            raise ValueError("variant or mode is unsupported")
        if self.expected_status not in _STATUSES or self.actual_status not in _STATUSES:
            raise ValueError("verification status is unsupported")
        if not 0 <= self.checks_completed <= self.checks_total or self.checks_total > 1_000:
            raise ValueError("verification checks are out of bounds")
        if not 0 <= self.model_calls <= 100:
            raise ValueError("model_calls is out of bounds")
        if _COMMIT.fullmatch(self.commit) is None:
            raise ValueError("commit MUST be a lowercase git object id")
        try:
            timestamp = datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("recorded_at MUST be ISO 8601") from exc
        if timestamp.tzinfo is None:
            raise ValueError("recorded_at MUST include a timezone")

    def to_dict(self) -> dict[str, object]:
        expected_reason_matches = (
            self.expected_reason is None or self.expected_reason == self.actual_reason
        )
        passed = (
            self.expected_authority == self.actual_authority
            and self.expected_status == self.actual_status
            and expected_reason_matches
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            **{field: getattr(self, field) for field in sorted(_FIELDS)},
            "passed": passed,
            "unexpected_unverified": (
                self.actual_status == "unverified" and self.expected_status != "unverified"
            ),
        }


def append_result(path: Path, result: CampaignResult) -> None:
    """Append one result with private local permissions and no symlink following."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("campaign result path MUST NOT be a symlink")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        line = json.dumps(
            result.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        _append_bytes(descriptor, f"{line}\n".encode())
    finally:
        os.close(descriptor)


def _append_bytes(descriptor: int, payload: bytes) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    original_size = os.lseek(descriptor, 0, os.SEEK_END)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("campaign result append made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except BaseException:
        os.ftruncate(descriptor, original_size)
        os.fsync(descriptor)
        raise
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _text(raw: object) -> str:
    if not isinstance(raw, str) or not 0 < len(raw) <= _MAX_TEXT:
        raise ValueError("campaign result text is invalid")
    return raw


def _optional_text(raw: object) -> str | None:
    return None if raw is None else _text(raw)


def _integer(raw: object) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("campaign result counter MUST be an integer")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".fdai/chat-assurance/results.jsonl"),
    )
    args = parser.parse_args(argv)
    appended = 0
    stream = sys.stdin.buffer
    while line := stream.readline(_MAX_INPUT_BYTES + 1):
        if len(line) > _MAX_INPUT_BYTES:
            raise ValueError("campaign result input line exceeds the byte limit")
        if not line.strip():
            continue
        raw: Any = json.loads(line)
        if not isinstance(raw, Mapping):
            raise ValueError("campaign result input MUST be a JSON object")
        append_result(args.output, CampaignResult.from_mapping(raw))
        appended += 1
    print(json.dumps({"appended": appended, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
