"""Tests for the trusted Check Run governance authority gate."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).parents[3]
_SCRIPT = _ROOT / "scripts/governance/check-governance-review-authority.py"
_CI_WORKFLOW = _ROOT / ".github/workflows/ci.yml"


def test_ci_prefilter_routes_retirement_changes_to_authority_check() -> None:
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")

    assert "rule-sets|assignments|exemptions|overrides|retirements" in workflow
    assert "config/notifications-matrix\\.yaml" in workflow
    assert "git diff --no-renames --name-only" in workflow


_HEAD = "a" * 40
_APP_ID = 42
_COMMITTED = datetime(2026, 8, 23, tzinfo=UTC)


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_governance_review_authority", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _principal(login: str, oid: str, role: str, *, phishing: bool = True) -> dict[str, object]:
    return {
        "github_login": login,
        "oid": oid,
        "roles": [role],
        "reviewed_revision": _HEAD,
        "attested_at": (_COMMITTED + timedelta(minutes=10)).isoformat(),
        "phishing_resistant": phishing,
    }


def _write_inputs(
    tmp_path: Path,
    *,
    changed_path: str,
    reviewers: tuple[tuple[str, str, str], ...],
    author_login: str = "author",
    trusted_app_id: int = _APP_ID,
    co_author_oids: tuple[str, ...] = (),
    committer_oids: tuple[str, ...] = (),
) -> list[str]:
    event = {
        "pull_request": {
            "user": {"login": author_login},
            "head": {"sha": _HEAD},
        }
    }
    commit = {"commit": {"committer": {"date": _COMMITTED.isoformat()}}}
    reviews = [
        {
            "user": {"login": login},
            "state": "APPROVED",
            "commit_id": _HEAD,
            "submitted_at": (_COMMITTED + timedelta(minutes=5)).isoformat(),
        }
        for login, _, _ in reviewers
    ]
    bundle = {
        "schema_version": "1.0.0",
        "head_revision": _HEAD,
        "principals": [
            _principal(author_login, "oid-author", "Contributor"),
            *[_principal(login, oid, role) for login, oid, role in reviewers],
        ],
        "co_author_oids": list(co_author_oids),
        "committer_oids": list(committer_oids),
    }
    checks = {
        "check_runs": [
            {
                "id": 1,
                "name": "FDAI Governance Identity Attestation",
                "head_sha": _HEAD,
                "status": "completed",
                "conclusion": "success",
                "completed_at": (_COMMITTED + timedelta(minutes=11)).isoformat(),
                "app": {"id": trusted_app_id},
                "output": {"summary": json.dumps(bundle)},
            }
        ]
    }
    values = {
        "event.json": event,
        "commit.json": commit,
        "reviews.json": reviews,
        "checks.json": checks,
    }
    for name, value in values.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "changed.txt").write_text(changed_path + "\n", encoding="utf-8")
    return [
        "--event",
        str(tmp_path / "event.json"),
        "--commit",
        str(tmp_path / "commit.json"),
        "--reviews",
        str(tmp_path / "reviews.json"),
        "--checks",
        str(tmp_path / "checks.json"),
        "--changed-files",
        str(tmp_path / "changed.txt"),
        "--trusted-app-id",
        str(_APP_ID),
    ]


def test_rule_authoring_accepts_one_attested_approver(gate: ModuleType, tmp_path: Path) -> None:
    argv = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/rules/example.yaml",
        reviewers=(("reviewer", "oid-reviewer", "Approver"),),
    )

    assert gate.main(argv) == 0


def test_assignment_change_requires_two_attested_approvers(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    argv = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/governance/assignments/example.yaml",
        reviewers=(("reviewer", "oid-reviewer", "Approver"),),
    )

    assert gate.main(argv) == 1


@pytest.mark.parametrize(
    "changed_path",
    (
        "rule-catalog/governance/assignments/example.yaml",
        "rule-catalog/exemptions/example.json",
        "rule-catalog/overrides/example.yaml",
        "config/notifications-matrix.yaml",
    ),
)
def test_high_risk_governance_classes_require_two_distinct_approvers(
    gate: ModuleType,
    tmp_path: Path,
    changed_path: str,
) -> None:
    under_quorum = _write_inputs(
        tmp_path,
        changed_path=changed_path,
        reviewers=(("reviewer-one", "oid-reviewer-1", "Owner"),),
    )
    assert gate.main(under_quorum) == 1

    quorum = _write_inputs(
        tmp_path,
        changed_path=changed_path,
        reviewers=(
            ("reviewer-one", "oid-reviewer-1", "Owner"),
            ("reviewer-two", "oid-reviewer-2", "Owner"),
        ),
    )
    assert gate.main(quorum) == 0


def test_untrusted_check_run_app_is_rejected(gate: ModuleType, tmp_path: Path) -> None:
    argv = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/rules/example.yaml",
        reviewers=(("reviewer", "oid-reviewer", "Approver"),),
        trusted_app_id=_APP_ID + 1,
    )

    assert gate.main(argv) == 1


def test_trusted_check_run_can_arrive_on_a_later_page(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    argv = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/rules/example.yaml",
        reviewers=(("reviewer", "oid-reviewer", "Approver"),),
    )
    checks_path = tmp_path / "checks.json"
    trusted_page = json.loads(checks_path.read_text(encoding="utf-8"))
    unrelated_page = {
        "check_runs": [
            {
                "id": item,
                "name": f"unrelated-{item}",
                "head_sha": _HEAD,
                "app": {"id": _APP_ID},
            }
            for item in range(100)
        ]
    }
    checks_path.write_text(
        json.dumps([unrelated_page, trusted_page]),
        encoding="utf-8",
    )

    assert gate.main(argv) == 0


def test_author_self_approval_is_rejected(gate: ModuleType, tmp_path: Path) -> None:
    argv = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/rules/example.yaml",
        reviewers=(("author", "oid-author", "Approver"),),
    )

    assert gate.main(argv) == 1


@pytest.mark.parametrize(
    ("identity_kind", "identity_kwargs"),
    (
        ("coauthor", {"co_author_oids": ("oid-reviewer-1",)}),
        ("committer", {"committer_oids": ("oid-reviewer-1",)}),
    ),
)
def test_a1_routing_rejects_coauthor_and_committer_self_approval(
    gate: ModuleType,
    tmp_path: Path,
    identity_kind: str,
    identity_kwargs: dict[str, tuple[str, ...]],
) -> None:
    del identity_kind
    argv = _write_inputs(
        tmp_path,
        changed_path="config/notifications-matrix.yaml",
        reviewers=(
            ("reviewer-one", "oid-reviewer-1", "Owner"),
            ("reviewer-two", "oid-reviewer-2", "Owner"),
        ),
        **identity_kwargs,
    )

    assert gate.main(argv) == 1


def test_rule_retirement_change_requires_two_phishing_resistant_owner_approvers(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    """A retirement's blast radius is global, not resource-scoped: it MUST NOT be
    able to merge under the single-approver rule-authoring bar, and it MUST clear
    only with an Owner-tier approval among its quorum of two."""

    under_quorum = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/retirements/example.yaml",
        reviewers=(("reviewer", "oid-reviewer", "Approver"),),
    )
    assert gate.main(under_quorum) == 1

    no_owner = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/retirements/example.yaml",
        reviewers=(
            ("reviewer-one", "oid-reviewer-1", "Approver"),
            ("reviewer-two", "oid-reviewer-2", "Approver"),
        ),
    )
    assert gate.main(no_owner) == 1

    cleared = _write_inputs(
        tmp_path,
        changed_path="rule-catalog/retirements/example.yaml",
        reviewers=(
            ("reviewer-one", "oid-reviewer-1", "Approver"),
            ("owner-one", "oid-owner-1", "Owner"),
        ),
    )
    assert gate.main(cleared) == 0
