#!/usr/bin/env python3
"""Verify a GitHub Environment matches the declared deployment approval policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def required_approvals_for_environment(
    environment: str,
    *,
    dev_required_approvals: int,
) -> int:
    """Resolve the configurable dev policy while keeping later environments protected."""

    if environment not in {"dev", "staging", "prod"}:
        raise ValueError("deployment environment is unsupported")
    if dev_required_approvals not in {0, 1}:
        raise ValueError("dev required approvals must be zero or one")
    return dev_required_approvals if environment == "dev" else 1


def verify(payload: object, *, required_approvals: int) -> None:
    """Require either an explicit no-review policy or one independent approval."""

    if required_approvals not in {0, 1}:
        raise ValueError("GitHub Environment supports zero or one required approval")
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
    if required_approvals == 0:
        if reviewer_rules:
            raise ValueError("GitHub Environment MUST omit required reviewers")
        return
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
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--required-approvals", type=int)
    policy.add_argument("--environment", choices=("dev", "staging", "prod"))
    parser.add_argument("--dev-required-approvals", type=int, default=1)
    args = parser.parse_args()
    required_approvals = args.required_approvals
    if required_approvals is None:
        if args.environment is None:
            parser.error("--required-approvals or --environment is required")
        required_approvals = required_approvals_for_environment(
            args.environment,
            dev_required_approvals=args.dev_required_approvals,
        )
    with args.environment_json.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    verify(payload, required_approvals=required_approvals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
