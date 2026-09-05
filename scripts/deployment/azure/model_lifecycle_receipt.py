#!/usr/bin/env python3
"""Build a governed draft-only receipt for one model lifecycle proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_COMMIT = re.compile(r"^[a-f0-9]{40}$")


def build_model_lifecycle_receipt(
    *,
    proposal: Mapping[str, object],
    pull_request: Mapping[str, object],
    source_commit: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
) -> dict[str, object]:
    """Bind sanitized evidence to an immutable draft PR with no authority."""

    proposal_digest = _verified_proposal_digest(proposal)
    source_models_digest = proposal.get("source_models_digest")
    if not isinstance(source_models_digest, str) or _DIGEST.fullmatch(source_models_digest) is None:
        raise ValueError("proposal source_models_digest is invalid")
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("receipt source_commit is invalid")
    number = pull_request.get("number")
    head_sha = pull_request.get("headRefOid")
    if (
        pull_request.get("isDraft") is not True
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or not isinstance(head_sha, str)
        or _COMMIT.fullmatch(head_sha) is None
    ):
        raise ValueError("receipt requires an immutable draft pull request")
    if not workflow_run_id.isdigit() or workflow_run_attempt < 1:
        raise ValueError("receipt workflow identity is invalid")
    body: dict[str, object] = {
        "schema_version": "fdai.model-lifecycle-reconciliation-receipt.v1",
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "source_commit": source_commit,
        "source_models_digest": source_models_digest,
        "proposal_digest": proposal_digest,
        "proposal_path": f"config/model-lifecycle-proposals/{proposal_digest}.json",
        "pull_request": number,
        "head_sha": head_sha,
        "draft": True,
        "evidence_sanitized": True,
        "activation_authority": False,
        "mapping_authority": False,
        "execution_authority": False,
        "live_execution_eligible": False,
        "required_next_gate": "human_review_and_merge",
    }
    body["receipt_digest"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return body


def _verified_proposal_digest(proposal: Mapping[str, object]) -> str:
    proposal_digest = proposal.get("proposal_digest")
    if not isinstance(proposal_digest, str) or _DIGEST.fullmatch(proposal_digest) is None:
        raise ValueError("proposal_digest is invalid")
    digest_input = dict(proposal)
    digest_input["proposal_digest"] = None
    observed = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if observed != proposal_digest:
        raise ValueError("proposal digest verification failed")
    if proposal.get("status") != "proposal" or proposal.get("activation_authority") is not False:
        raise ValueError("receipt accepts sanitized draft proposals only")
    return proposal_digest


def _load_object(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--pull-request", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_model_lifecycle_receipt(
            proposal=_load_object(args.proposal),
            pull_request=_load_object(args.pull_request),
            source_commit=args.source_commit,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
