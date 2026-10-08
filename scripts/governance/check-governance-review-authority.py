#!/usr/bin/env python3
"""Validate governance PR authority from GitHub facts and a trusted Check Run.

The trusted GitHub App performs Entra identity, role, and authentication-assurance
verification outside this repository. Its exact-head Check Run carries a bounded JSON
attestation in ``output.summary``. This consumer cross-checks that attestation against
GitHub's PR, commit, and review records before invoking the pure authority decision.

A change to the notification matrix is A1 routing, and needs that attestation, only when it can
change decision-bearing routing. ``--scope-only`` reports that scope before CI requires the
trusted App, so ordinary A2 to A4 route additions follow normal review while every A1 routing
change still fails closed without the App.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fdai.core.notifications.matrix import load_matrix_from_mapping
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
from fdai.runtime.approval_profile import load_approval_profile
from fdai.shared.providers.notifications.base import TrustTier

_MAX_INPUT_BYTES = 1024 * 1024
_MAX_REVIEWS = 64
_MAX_CHECK_RUNS = 512
_CHECK_NAME = "FDAI Governance Identity Attestation"
_MATRIX_PATH = "config/notifications-matrix.yaml"
_OVERRIDE_BOUNDS_PATH = "rule-catalog/override-parameter-bounds.yaml"
# Files whose behavior makes a non-A1 matrix change safe. A pull request that changes any of them
# can't also use the non-A1 matrix scope, because it could weaken the proof it relies on.
SCOPE_TRUST_ANCHORS = frozenset(
    {
        ".github/workflows/ci.yml",
        "scripts/governance/check-governance-review-authority.py",
        "services/core-control-plane/src/fdai/core/notifications/matrix.py",
        "services/core-control-plane/src/fdai/core/notifications/router.py",
        "services/core-control-plane/src/fdai/shared/providers/notifications/base.py",
        "services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py",
        "services/core-control-plane/src/fdai/delivery/gitops_pr/governance_review.py",
    }
)
_MAX_MATRIX_BYTES = 256 * 1024


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


class _StrictLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate mapping keys."""


def _strict_mapping(
    loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _strict_mapping,
)


def _strict_yaml(text: str) -> object:
    """Parse ``text`` with no anchors, aliases, merge keys, or duplicate keys."""
    if len(text.encode("utf-8")) > _MAX_MATRIX_BYTES:
        raise ValueError("matrix exceeds its size limit")
    for token in yaml.scan(text, Loader=yaml.SafeLoader):
        if isinstance(token, yaml.AnchorToken | yaml.AliasToken):
            raise ValueError("matrix MUST NOT use anchors or aliases")
    if "<<:" in text:
        raise ValueError("matrix MUST NOT use merge keys")
    return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass


def matrix_change_is_a1_routing(base_text: str | None, head_text: str | None) -> bool:
    """Return whether a matrix change can alter decision-bearing (A1) routing.

    Fails closed: a missing side, a parse or validation error, or any change outside
    ``matrix.routes`` is A1 routing. Inside the routes, removing a route, changing the default
    route, or adding or changing a route that is A1 before or after the change is A1 routing.
    The router separately refuses to deliver an A1 message through a non-A1 route.
    """
    try:
        if base_text is None or head_text is None:
            return True
        base, head = _strict_yaml(base_text), _strict_yaml(head_text)
        if not isinstance(base, Mapping) or not isinstance(head, Mapping):
            return True
        base_matrix = load_matrix_from_mapping(base)
        head_matrix = load_matrix_from_mapping(head)
        base_rest, head_rest = copy.deepcopy(dict(base)), copy.deepcopy(dict(head))
        base_routes = base_rest["matrix"].pop("routes")
        head_routes = head_rest["matrix"].pop("routes")
        if base_rest != head_rest:
            return True
        for name in sorted(set(base_routes) | set(head_routes), key=str):
            before, after = base_routes.get(name), head_routes.get(name)
            if before == after:
                continue
            if after is None or name in (base_matrix.default_route, head_matrix.default_route):
                return True
            tiers = [head_matrix.routes[name].trust_tier]
            if before is not None:
                tiers.append(base_matrix.routes[name].trust_tier)
            if TrustTier.A1_HIL_APPROVAL in tiers:
                return True
        return False
    except Exception:  # noqa: BLE001 - any doubt is A1 routing
        return True


def _git_blob(revision: str, path: str) -> str | None:
    proc = subprocess.run(  # noqa: S603 - fixed git argv with validated revisions
        ["git", "show", f"{revision}:{path}"],  # noqa: S607 - git resolved from PATH
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0 or len(proc.stdout) > _MAX_MATRIX_BYTES:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _merge_base(base_sha: str, head_sha: str) -> str | None:
    for revision in (base_sha, head_sha):
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            return None
    proc = subprocess.run(  # noqa: S603 - fixed git argv with validated revisions
        ["git", "merge-base", base_sha, head_sha],  # noqa: S607 - git resolved from PATH
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    merge_base = proc.stdout.strip()
    return merge_base if proc.returncode == 0 and len(merge_base) == 40 else None


def matrix_is_a1_routing(base_sha: str | None, head_sha: str | None) -> bool:
    """Classify the matrix change between the merge base and the PR head."""
    if not base_sha or not head_sha:
        return True
    merge_base = _merge_base(base_sha, head_sha)
    if merge_base is None:
        return True
    return matrix_change_is_a1_routing(
        _git_blob(merge_base, _MATRIX_PATH), _git_blob(head_sha, _MATRIX_PATH)
    )


def _change_classes(
    paths: Sequence[str], *, matrix_a1_routing: bool = True
) -> tuple[GovernanceChangeClass, ...]:
    classes: set[GovernanceChangeClass] = set()
    for path in paths:
        normalized = path.strip().replace("\\", "/")
        if not normalized:
            continue
        if normalized == _OVERRIDE_BOUNDS_PATH:
            classes.add(GovernanceChangeClass.OVERRIDE)
        elif normalized == _MATRIX_PATH:
            # A1 routing is an authority override: changing its primary or
            # fallback can change who receives a decision-bearing callback.
            # Other routes are ordinary routing configuration.
            if matrix_a1_routing:
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
    parser.add_argument("--scope-only", action="store_true")
    parser.add_argument("--event", type=Path)
    parser.add_argument("--commit", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--trusted-app-id", type=int)
    parser.add_argument("--base-sha", help="pull-request base revision")
    parser.add_argument("--head-sha", help="pull-request head revision")
    args = parser.parse_args(argv)

    paths = args.changed_files.read_text(encoding="utf-8").splitlines()
    normalized_paths = {path.strip().replace("\\", "/") for path in paths}
    matrix_changed = _MATRIX_PATH in normalized_paths
    matrix_a1 = (
        bool(normalized_paths & SCOPE_TRUST_ANCHORS)
        or matrix_is_a1_routing(args.base_sha, args.head_sha)
        if matrix_changed
        else True
    )
    classes = _change_classes(paths, matrix_a1_routing=matrix_a1)
    if args.scope_only:
        print(
            json.dumps(
                {
                    "identity_review_required": bool(classes),
                    "classes": [item.value for item in classes],
                    "matrix_a1_routing": matrix_changed and matrix_a1,
                }
            )
        )
        return 0
    missing = [
        name
        for name in ("event", "commit", "reviews", "checks", "trusted_app_id")
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")

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
                    approval_profile=load_approval_profile(os.environ),
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
