"""Deterministic diff-analysis tests."""

from __future__ import annotations

from fdai_code_assurance.analyzer import analyze_snapshot
from fdai_code_assurance.models import PullRequestFile, PullRequestSnapshot, ReviewProfile

_BASE = "a" * 40
_HEAD = "b" * 40


def _snapshot(patch: str | None) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        repository="example/project",
        pull_number=7,
        base_sha=_BASE,
        head_sha=_HEAD,
        changed_files=1,
        files=(
            PullRequestFile(
                path="src/example.py",
                status="modified",
                additions=2,
                deletions=1,
                patch=patch,
            ),
        ),
    )


def test_security_review_reports_new_line_without_exposing_secret() -> None:
    secret = "not-a-real-secret-value"
    report = analyze_snapshot(
        _snapshot(f"@@ -10,2 +10,2 @@\n-old = None\n+api_key = '{secret}'\n context = True"),
        profile=ReviewProfile.SECURITY,
    )

    finding = report.findings[0]
    assert finding.rule_id == "security.secret-literal"
    assert finding.line == 10
    assert secret not in str(report.to_dict())
    assert len(finding.evidence_sha256) == 64


def test_code_profile_excludes_security_only_rules() -> None:
    report = analyze_snapshot(
        _snapshot("@@ -1 +1,2 @@\n context = True\n+verify=False\n+def collect(items=[]):"),
        profile=ReviewProfile.CODE,
    )

    assert [finding.rule_id for finding in report.findings] == ["code.mutable-default"]


def test_missing_patch_is_reported_as_omitted_coverage() -> None:
    report = analyze_snapshot(_snapshot(None), profile=ReviewProfile.ALL)

    assert report.reviewed_files == 0
    assert report.omitted_patch_files == ("src/example.py",)
    assert report.findings == ()
    assert report.to_dict()["coverage_complete"] is False


def test_empty_patch_is_not_counted_as_reviewed() -> None:
    report = analyze_snapshot(_snapshot(""), profile=ReviewProfile.ALL)

    assert report.reviewed_files == 0
    assert report.to_dict()["changed_files"] == 1
    assert report.to_dict()["coverage_complete"] is False


def test_safe_yaml_loader_is_not_reported() -> None:
    report = analyze_snapshot(
        _snapshot("@@ -1 +1 @@\n+value = yaml.load(document, Loader=yaml.SafeLoader)"),
        profile=ReviewProfile.SECURITY,
    )

    assert report.findings == ()


def test_commented_bare_except_is_reported() -> None:
    report = analyze_snapshot(
        _snapshot("@@ -1 +1 @@\n+except:  # fallback"),
        profile=ReviewProfile.CODE,
    )

    assert [finding.rule_id for finding in report.findings] == ["code.bare-except"]
