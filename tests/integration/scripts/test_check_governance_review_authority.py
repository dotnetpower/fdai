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
    assert "rule-catalog/risk-classification\\.yaml$" in workflow
    assert ".*risk-classification" not in workflow
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


_MATRIX = (_ROOT / "config" / "notifications-matrix.yaml").read_text(encoding="utf-8")
_A2_ROUTE = """
    fixture_only_a2_alert:
      trust_tier: a2_operational_alert
      delivery_mode: fanout
      channels:
        - teams-ops-prd
      on_all_fail: hil_escalate
"""


def _with_route(text: str, route: str) -> str:
    return text.replace("\n  routes:\n", "\n  routes:\n" + route.lstrip("\n"), 1)


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (_with_route(_MATRIX, _A2_ROUTE), False),
        (_MATRIX.replace("# FDAI notification routing matrix.", "# Routing matrix."), False),
        (_with_route(_MATRIX, _A2_ROUTE.replace("a2_operational_alert", "a1_hil_approval")), True),
        (_with_route(_MATRIX, _A2_ROUTE.replace("a2_operational_alert", "A1_HIL_APPROVAL")), True),
        (_MATRIX.replace("primary: teams-hil-prd", "primary: teams-ops-prd", 1), True),
        (_MATRIX.replace("default_route: hil_approval", "default_route: adapter_health"), True),
        (
            _MATRIX.replace(
                "  routes:\n", "  channels:\n    teams-hil-prd: { locale: ko }\n  routes:\n", 1
            ),
            True,
        ),
        (_MATRIX.replace("    kill_switch_state:\n", "    removed_kill_switch_state:\n", 1), True),
        (_with_route(_MATRIX, _A2_ROUTE + _A2_ROUTE), True),
        (_with_route(_MATRIX, "    anchored: &a\n      trust_tier: a2_operational_alert\n"), True),
        ("matrix: [", True),
        (None, True),
    ],
)
def test_matrix_change_scope_fails_closed(
    gate: ModuleType, head: str | None, expected: bool
) -> None:
    assert gate.matrix_change_is_a1_routing(_MATRIX, head) is expected


def test_raising_a2_route_to_a1_is_a1_routing(gate: ModuleType) -> None:
    base = _with_route(_MATRIX, _A2_ROUTE)
    head = _with_route(_MATRIX, _A2_ROUTE.replace("a2_operational_alert", "a1_hil_approval"))
    assert gate.matrix_change_is_a1_routing(base, head) is True
    assert gate.matrix_change_is_a1_routing(None, base) is True


def _git(repo: Path, *args: str) -> str:
    import subprocess

    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(repo), "PATH": "/usr/bin:/bin"}
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_scope_only_compares_the_merge_base_with_the_head(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    matrix = repo / "config" / "notifications-matrix.yaml"
    matrix.write_text(_MATRIX, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "topic")
    matrix.write_text(_with_route(_MATRIX, _A2_ROUTE), encoding="utf-8")
    _git(repo, "commit", "-qam", "add a2 route")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    matrix.write_text(
        _MATRIX.replace("primary: teams-hil-prd", "primary: teams-ops-prd", 1), encoding="utf-8"
    )
    _git(repo, "commit", "-qam", "unrelated a1 change on the base")
    base = _git(repo, "rev-parse", "HEAD")
    changed = tmp_path / "changed.txt"
    changed.write_text("config/notifications-matrix.yaml\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    args = ["--scope-only", "--changed-files", str(changed), "--base-sha", base, "--head-sha", head]
    assert gate.main(args) == 0
    scope = json.loads(capsys.readouterr().out)
    assert scope == {"identity_review_required": False, "classes": [], "matrix_a1_routing": False}

    assert gate.main(["--scope-only", "--changed-files", str(changed)]) == 0
    assert json.loads(capsys.readouterr().out)["identity_review_required"] is True

    changed.write_text(
        "config/notifications-matrix.yaml\nrule-catalog/rules/x.yaml\n", encoding="utf-8"
    )
    assert gate.main(args) == 0
    assert json.loads(capsys.readouterr().out)["classes"] == ["rule-authoring"]


def test_ci_decides_scope_before_requiring_the_trusted_app() -> None:
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Enforce governance review authority", 1)[1].split(
        "\n      - name:", 1
    )[0]
    assert step.index("--scope-only") < step.index("FDAI_GOVERNANCE_IDENTITY_APP_ID must name")
    assert '--base-sha "$PR_BASE_SHA"' in step
    assert '--head-sha "$PR_HEAD_SHA"' in step


@pytest.mark.parametrize(
    "path",
    [
        "rule-catalog/rules/x.yaml",
        "rule-catalog/rule-sets/x.yaml",
        "rule-catalog/assignments/x.yaml",
        "rule-catalog/exemptions/x.yaml",
        "rule-catalog/overrides/x.yaml",
        "rule-catalog/retirements/x.yaml",
        "rule-catalog/override-parameter-bounds.yaml",
        "rule-catalog/risk-classification.yaml",
        "policies/risk/x.rego",
        "config/notifications-matrix.yaml",
    ],
)
def test_every_ci_governed_path_needs_identity_review_by_default(
    gate: ModuleType, path: str
) -> None:
    import re

    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    pattern = re.search(
        r"grep -Eq '(\^\(config/notifications-matrix[^']+)' \"\$changed\"", workflow
    )
    assert pattern is not None and re.match(pattern.group(1), path)
    assert gate._change_classes([path]) != ()


@pytest.mark.parametrize(
    "anchor",
    sorted(
        _SCOPE_ANCHORS := (
            ".github/workflows/ci.yml",
            "scripts/governance/check-governance-review-authority.py",
            "services/core-control-plane/src/fdai/core/notifications/matrix.py",
            "services/core-control-plane/src/fdai/core/notifications/router.py",
            "services/core-control-plane/src/fdai/shared/providers/notifications/base.py",
            "services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py",
            "services/core-control-plane/src/fdai/delivery/gitops_pr/governance_review.py",
        )
    ),
)
def test_changing_a_scope_trust_anchor_removes_the_non_a1_relaxation(
    gate: ModuleType,
    anchor: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import re

    assert anchor in gate.SCOPE_TRUST_ANCHORS
    step = _CI_WORKFLOW.read_text(encoding="utf-8").split(
        "- name: Enforce governance review authority", 1
    )[1]
    shell_pattern = re.search(r"grep -Eqx '([^']+)' \"\$changed\"", step)
    assert shell_pattern is not None and re.fullmatch(shell_pattern.group(1), anchor)
    monkeypatch.setattr(gate, "matrix_is_a1_routing", lambda base, head: False)
    changed = tmp_path / "changed.txt"
    changed.write_text(f"config/notifications-matrix.yaml\n{anchor}\n", encoding="utf-8")
    assert gate.main(["--scope-only", "--changed-files", str(changed)]) == 0
    assert json.loads(capsys.readouterr().out)["identity_review_required"] is True
    changed.write_text("config/notifications-matrix.yaml\n", encoding="utf-8")
    assert gate.main(["--scope-only", "--changed-files", str(changed)]) == 0
    assert json.loads(capsys.readouterr().out)["identity_review_required"] is False
