#!/usr/bin/env python3
"""Validate governance PR authority from GitHub facts and a trusted Check Run.

The trusted GitHub App performs Entra identity, role, and authentication-assurance
verification outside this repository. Its exact-head Check Run carries a bounded JSON
attestation in ``output.summary``. This consumer cross-checks that attestation against
GitHub's PR, commit, and review records before invoking the pure authority decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai.core.rbac.roles import Role
from fdai.delivery.gitops_pr.governance_review import (
    GitHubPullRequestReview,
    GitHubPullRequestReviewContext,
    VerifiedGitHubPrincipal,
    build_governance_review_request,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceChangeClass,
    validate_governance_review,
)

_MAX_INPUT_BYTES = 1024 * 1024
_MAX_REVIEWS = 64
_MAX_CHECK_RUNS = 512
_CHECK_NAME = "FDAI Governance Identity Attestation"


def _load_json(path: Path, name: str) -> object:
    if not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{name} MUST be a bounded regular JSON file")
    return json.loads(path.read_text(encoding="utf-8"))


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} MUST be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{name} MUST be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} MUST be non-empty text")
    return value.strip()


def _timestamp(value: object, name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")
    return parsed


def _reviews(value: object) -> tuple[GitHubPullRequestReview, ...]:
    items = _sequence(value, "reviews")
    if items and all(
        isinstance(item, Sequence) and not isinstance(item, str | bytes) for item in items
    ):
        items = tuple(page_item for page in items for page_item in _sequence(page, "review page"))
    if len(items) > _MAX_REVIEWS:
        raise ValueError("governance review count exceeds its limit")
    result: list[GitHubPullRequestReview] = []
    for item in items:
        raw = _object(item, "review")
        user = _object(raw.get("user"), "review user")
        result.append(
            GitHubPullRequestReview(
                reviewer_login=_text(user.get("login"), "review user login"),
                state=_text(raw.get("state"), "review state"),
                commit_id=_text(raw.get("commit_id"), "review commit id"),
                submitted_at=_timestamp(raw.get("submitted_at"), "review submitted_at"),
            )
        )
    return tuple(result)


def _attestation(
    checks_value: object,
    *,
    trusted_app_id: int,
    head_revision: str,
) -> Mapping[str, Any]:
    pages: tuple[Mapping[str, Any], ...]
    if isinstance(checks_value, Mapping):
        pages = (_object(checks_value, "check runs response"),)
    else:
        pages = tuple(
            _object(page, "check runs response page")
            for page in _sequence(checks_value, "check runs response pages")
        )
    checks = tuple(
        item for page in pages for item in _sequence(page.get("check_runs"), "check_runs")
    )
    if len(checks) > _MAX_CHECK_RUNS:
        raise ValueError("governance Check Run count exceeds its limit")
    matching: list[Mapping[str, Any]] = []
    for item in checks:
        check = _object(item, "check run")
        app = _object(check.get("app"), "check run app")
        if (
            check.get("name") == _CHECK_NAME
            and check.get("head_sha") == head_revision
            and app.get("id") == trusted_app_id
        ):
            matching.append(check)
    if not matching:
        raise ValueError("trusted exact-head governance identity Check Run is missing")
    latest = max(
        matching,
        key=lambda item: (
            _text(item.get("completed_at"), "check completed_at"),
            int(item.get("id", 0)),
        ),
    )
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("latest governance identity Check Run did not succeed")
    output = _object(latest.get("output"), "check run output")
    summary = _text(output.get("summary"), "check run output summary")
    if len(summary.encode("utf-8")) > _MAX_INPUT_BYTES:
        raise ValueError("governance identity attestation exceeds its limit")
    bundle = _object(json.loads(summary), "governance identity attestation")
    expected = {
        "schema_version",
        "head_revision",
        "principals",
        "co_author_oids",
        "committer_oids",
    }
    if set(bundle) != expected or bundle.get("schema_version") != "1.0.0":
        raise ValueError("governance identity attestation fields do not match schema")
    if bundle.get("head_revision") != head_revision:
        raise ValueError("governance identity attestation head revision mismatch")
    return bundle


def _principals(bundle: Mapping[str, Any]) -> tuple[VerifiedGitHubPrincipal, ...]:
    result: list[VerifiedGitHubPrincipal] = []
    for item in _sequence(bundle.get("principals"), "attested principals"):
        raw = _object(item, "attested principal")
        expected = {
            "github_login",
            "oid",
            "roles",
            "reviewed_revision",
            "attested_at",
            "phishing_resistant",
        }
        if set(raw) != expected:
            raise ValueError("attested principal fields do not match schema")
        phishing_resistant = raw.get("phishing_resistant")
        if not isinstance(phishing_resistant, bool):
            raise ValueError("attested principal phishing_resistant MUST be boolean")
        result.append(
            VerifiedGitHubPrincipal(
                github_login=_text(raw.get("github_login"), "principal github_login"),
                oid=_text(raw.get("oid"), "principal oid"),
                roles=frozenset(
                    Role(_text(role, "principal role"))
                    for role in _sequence(raw.get("roles"), "principal roles")
                ),
                reviewed_revision=_text(
                    raw.get("reviewed_revision"), "principal reviewed_revision"
                ),
                attested_at=_timestamp(raw.get("attested_at"), "principal attested_at"),
                phishing_resistant=phishing_resistant,
            )
        )
    if not result or len(result) > _MAX_REVIEWS + 1:
        raise ValueError("attested principal count is outside its bounded range")
    return tuple(result)


def _oid_set(value: object, name: str) -> frozenset[str]:
    items = _sequence(value, name)
    if len(items) > _MAX_REVIEWS:
        raise ValueError(f"{name} exceeds its limit")
    return frozenset(_text(item, name) for item in items)


def _change_classes(paths: Sequence[str]) -> tuple[GovernanceChangeClass, ...]:
    classes: set[GovernanceChangeClass] = set()
    for path in paths:
        normalized = path.strip().replace("\\", "/")
        if not normalized:
            continue
        if normalized == "config/notifications-matrix.yaml":
            # A1 routing is an authority override: changing its primary or
            # fallback can change who receives a decision-bearing callback.
            classes.add(GovernanceChangeClass.OVERRIDE)
        elif "/exemptions/" in f"/{normalized}":
            classes.add(GovernanceChangeClass.EXEMPTION)
        elif "/overrides/" in f"/{normalized}":
            classes.add(GovernanceChangeClass.OVERRIDE)
        elif "/retirements/" in f"/{normalized}":
            classes.add(GovernanceChangeClass.RULE_RETIREMENT)
        elif "/assignments/" in f"/{normalized}":
            classes.add(GovernanceChangeClass.ENFORCE_PROMOTION)
        elif normalized.startswith("policies/risk") or "risk-classification" in normalized:
            classes.add(GovernanceChangeClass.RISK_CLASSIFICATION_LOOSENING)
        elif normalized.startswith("rule-catalog/rules/") or normalized.startswith(
            "rule-catalog/rule-sets/"
        ):
            classes.add(GovernanceChangeClass.RULE_AUTHORING)
    return tuple(sorted(classes, key=lambda item: item.value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governance PR review-authority CI gate.")
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--commit", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--trusted-app-id", type=int, required=True)
    args = parser.parse_args(argv)

    try:
        event = _object(_load_json(args.event, "GitHub event"), "GitHub event")
        pull_request = _object(event.get("pull_request"), "pull_request")
        author = _object(pull_request.get("user"), "pull_request user")
        head = _object(pull_request.get("head"), "pull_request head")
        head_revision = _text(head.get("sha"), "pull_request head sha")
        commit = _object(_load_json(args.commit, "GitHub commit"), "GitHub commit")
        commit_details = _object(commit.get("commit"), "commit details")
        committer = _object(commit_details.get("committer"), "commit committer")
        reviews = _reviews(_load_json(args.reviews, "GitHub reviews"))
        bundle = _attestation(
            _load_json(args.checks, "GitHub check runs"),
            trusted_app_id=args.trusted_app_id,
            head_revision=head_revision,
        )
        classes = _change_classes(args.changed_files.read_text(encoding="utf-8").splitlines())
        if not classes:
            print("check-governance-review-authority: no governed catalog changes")
            return 0
        context = GitHubPullRequestReviewContext(
            author_login=_text(author.get("login"), "pull_request author login"),
            head_revision=head_revision,
            head_committed_at=_timestamp(committer.get("date"), "head commit time"),
            reviews=reviews,
            co_author_oids=_oid_set(bundle.get("co_author_oids"), "co_author_oids"),
            committer_oids=_oid_set(bundle.get("committer_oids"), "committer_oids"),
        )
        principals = _principals(bundle)
        decisions = tuple(
            validate_governance_review(
                build_governance_review_request(
                    change_class=change_class,
                    context=context,
                    verified_principals=principals,
                )
            )
            for change_class in classes
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"check-governance-review-authority: FAILED: {exc}", file=sys.stderr)
        return 1

    failed = False
    for decision in decisions:
        if decision.allowed:
            print(
                "check-governance-review-authority: "
                f"{decision.change_class.value}: OK ({decision.satisfied_quorum}/"
                f"{decision.required_quorum})"
            )
            continue
        failed = True
        print(
            f"check-governance-review-authority: {decision.change_class.value}: FAILED",
            file=sys.stderr,
        )
        for issue in decision.issues:
            print(f"  {issue.code}: {issue.message}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
