#!/usr/bin/env python3
"""Record a bounded batch of independent Cost Governance review decisions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MAX_INPUT_BYTES = 64 * 1024
_MAX_TARGETS = 6
_MAX_RATIONALE_CHARS = 2_000
_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_BATCH_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CHILD_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,399}$")
_TARGET_KINDS = frozenset({"package-activation", "action-type", "workflow"})
_DECISIONS = frozenset({"recommend", "hold", "deny"})
_SINGLE_REVIEW_SCRIPT = Path(__file__).with_name("record_cost_governance_review.py")


class BatchReviewError(ValueError):
    """The review envelope or one child review is invalid."""


@dataclass(frozen=True, slots=True)
class ReviewDirective:
    target_kind: str
    target_id: str
    decision: str
    rationale: str


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BatchReviewError("review batch JSON contains duplicate keys")
        value[key] = item
    return value


def load_review_batch(path: Path) -> tuple[ReviewDirective, ...]:
    """Load one bounded per-target review envelope without campaign evidence."""

    try:
        details = path.lstat()
    except OSError as exc:
        raise BatchReviewError("review batch file is unavailable") from exc
    if path.is_symlink() or not path.is_file() or details.st_size > _MAX_INPUT_BYTES:
        raise BatchReviewError("review batch file is not a bounded regular file")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchReviewError("review batch file is not valid UTF-8 JSON") from exc
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_TARGETS:
        raise BatchReviewError("review batch MUST contain 1..6 target decisions")

    directives: list[ReviewDirective] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {
            "target_kind",
            "target_id",
            "decision",
            "rationale",
        }:
            raise BatchReviewError(f"review batch target {index} fields are invalid")
        target_kind = raw["target_kind"]
        target_id = raw["target_id"]
        decision = raw["decision"]
        rationale = raw["rationale"]
        if target_kind not in _TARGET_KINDS:
            raise BatchReviewError(f"review batch target {index} kind is invalid")
        if not isinstance(target_id, str) or _TARGET_ID.fullmatch(target_id) is None:
            raise BatchReviewError(f"review batch target {index} id is invalid")
        if decision not in _DECISIONS:
            raise BatchReviewError(f"review batch target {index} decision is invalid")
        if (
            not isinstance(rationale, str)
            or not rationale.strip()
            or len(rationale) > _MAX_RATIONALE_CHARS
        ):
            raise BatchReviewError(f"review batch target {index} rationale is invalid")
        identity = (target_kind, target_id)
        if identity in identities:
            raise BatchReviewError("review batch target identities MUST be unique")
        identities.add(identity)
        directives.append(
            ReviewDirective(
                target_kind=target_kind,
                target_id=target_id,
                decision=decision,
                rationale=rationale,
            )
        )
    return tuple(directives)


def _child_request_id(batch_request_id: str, directive: ReviewDirective) -> str:
    child = f"{batch_request_id}:{directive.target_kind}:{directive.target_id}"
    if _CHILD_REQUEST_ID.fullmatch(child) is None:
        raise BatchReviewError("derived child review request id is invalid")
    return child


def record_review_batch(
    *,
    readiness: Path,
    policy: Path,
    batch_file: Path,
    request_id: str,
    evidence_refs: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Decompose one review envelope into existing independent review records."""

    if _BATCH_REQUEST_ID.fullmatch(request_id) is None:
        raise BatchReviewError("batch review request id is invalid")
    if not evidence_refs:
        raise BatchReviewError("batch review requires at least one evidence reference")

    reviews: list[dict[str, object]] = []
    inserted_any = False
    for directive in load_review_batch(batch_file):
        command = [
            sys.executable,
            os.fspath(_SINGLE_REVIEW_SCRIPT),
            "--readiness",
            os.fspath(readiness),
            "--policy",
            os.fspath(policy),
            "--target-kind",
            directive.target_kind,
            "--target-id",
            directive.target_id,
            "--decision",
            directive.decision,
            "--rationale",
            directive.rationale,
            "--request-id",
            _child_request_id(request_id, directive),
        ]
        for evidence_ref in evidence_refs:
            command.extend(("--evidence-ref", evidence_ref))
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise BatchReviewError(
                "child review failed for "
                f"{directive.target_kind}:{directive.target_id} "
                f"with exit code {completed.returncode}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BatchReviewError("child review returned invalid JSON") from exc
        if not isinstance(result, dict) or not isinstance(result.get("review"), dict):
            raise BatchReviewError("child review returned an invalid result")
        review = result["review"]
        if (
            review.get("target_kind") != directive.target_kind
            or review.get("target_id") != directive.target_id
            or review.get("approval_authority") is not False
            or review.get("execution_authority") is not False
            or review.get("promotion_authority") is not False
        ):
            raise BatchReviewError("child review violated its target or authority boundary")
        inserted = result.get("inserted")
        if not isinstance(inserted, bool):
            raise BatchReviewError("child review returned an invalid insert disposition")
        inserted_any = inserted_any or inserted
        reviews.append({**review, "inserted": inserted})
    return {
        "schema_version": "fdai.cost-governance-review-batch.v1",
        "batch_request_id": request_id,
        "inserted": inserted_any,
        "reviews": reviews,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--review-batch-json", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--evidence-ref", action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = record_review_batch(
            readiness=args.readiness,
            policy=args.policy,
            batch_file=args.review_batch_json,
            request_id=args.request_id,
            evidence_refs=tuple(args.evidence_ref),
        )
    except BatchReviewError as exc:
        print(f"cost-review-batch: ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
