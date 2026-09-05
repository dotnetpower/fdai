#!/usr/bin/env python3
"""Verify one GitHub Environment can enforce independent deployment approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(payload: object, *, required_approvals: int) -> None:
    """Require one enforceable reviewer approval with self-review blocked."""

    if required_approvals != 1:
        raise ValueError("GitHub Environment supports exactly one required approval")
    if not isinstance(payload, dict):
        raise ValueError("GitHub Environment response MUST be an object")
    if payload.get("can_admins_bypass") is not False:
        raise ValueError("GitHub Environment MUST disable admin bypass")
    rules = payload.get("protection_rules")
    if not isinstance(rules, list):
        raise ValueError("GitHub Environment protection rules are unavailable")
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    if len(reviewer_rules) != 1:
        raise ValueError("GitHub Environment required reviewers are unavailable")
    rule = reviewer_rules[0]
    reviewers = rule.get("reviewers")
    if (
        not isinstance(reviewers, list)
        or not reviewers
        or any(not isinstance(item, dict) for item in reviewers)
    ):
        raise ValueError("GitHub Environment required reviewers are invalid")
    if rule.get("prevent_self_review") is not True:
        raise ValueError("GitHub Environment MUST block self-review")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment_json", type=Path)
    parser.add_argument("--required-approvals", type=int, default=1)
    args = parser.parse_args()
    with args.environment_json.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    verify(payload, required_approvals=args.required_approvals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
