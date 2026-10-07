"""Tests for code-security review packages and notification planning."""

from __future__ import annotations

import json

import pytest
from fdai.core.notifications.renderer import NotificationCatalog
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.notify import (
    ALERT_CATEGORY,
    DIGEST_CATEGORY,
    NotificationPlanError,
    plan_code_security_notifications,
)
from fdai.core.security.code_findings.review_signal import (
    CodeSecurityReviewError,
    build_review_package,
    code_security_drift_payload,
    validate_review_package,
)
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.rule_catalog.code_security import Exposure

from ._support import REVISION, catalog, result, sarif

_ROUTES = {ALERT_CATEGORY, DIGEST_CATEGORY, "hil_approval"}


def _issues(*, kev: bool = False):  # type: ignore[no-untyped-def]
    raw = sarif(
        "Scanner",
        [
            result("sqli", "src/secret_module/db.py", 4, cwe=89, message="leak me"),
            result(
                "CVE-2024-66666",
                "package-lock.json",
                1,
                properties={"packageName": "libk", "security-severity": "8.0"},
            ),
        ],
    )
    occurrences = ingest_sarif(
        raw, SarifIngestContext(lane=Lane.EXTERNAL, revision=REVISION)
    ).occurrences
    known = frozenset({"CVE-2024-66666"}) if kev else frozenset()
    return build_issues(
        occurrences, catalog(), AnalysisContext(revision=REVISION, known_exploited=known)
    )


def _package(*, kev: bool = False, complete: bool = True, issues=None):  # type: ignore[no-untyped-def]
    return build_review_package(
        _issues(kev=kev) if issues is None else issues,
        repository_alias="example-service",
        revision=REVISION,
        exposure=Exposure.UNKNOWN,
        coverage_complete=complete,
    )


def test_package_and_drift_carry_counts_but_no_code_details() -> None:
    package = _package()
    drift = code_security_drift_payload(package)
    text = json.dumps(drift)
    assert "secret_module" not in text and "leak me" not in text and "libk" not in text
    assert drift["authority_ceiling"] == "shadow" and drift["grants_authority"] is False
    assert drift["decision"] == "open"
    assert drift["issue_count"] == 2
    assert drift["idempotency_key"].startswith("code-security-drift:")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(grants_authority=True), "authority"),
        (lambda p: p.update(issue_count=5), "add up"),
        (lambda p: p.update(revision="main"), "revision"),
        (lambda p: p.update(top_issue_ids=["../x"]), "top_issue_ids"),
        (lambda p: p.update(extra="x"), "fields"),
    ],
)
def test_invalid_packages_are_rejected(mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    package = dict(_package())
    mutate(package)
    with pytest.raises(CodeSecurityReviewError, match=message):
        validate_review_package(package)


def test_known_exploited_triggers_alert_and_digest() -> None:
    messages = plan_code_security_notifications(_package(kev=True), routes=_ROUTES)
    assert [(m.category, m.template_key) for m in messages] == [
        (ALERT_CATEGORY, "code_security_alert"),
        (DIGEST_CATEGORY, "code_security_digest"),
    ]
    assert all("secret_module" not in m.body_markdown for m in messages)
    assert code_security_drift_payload(_package(kev=True))["decision"] == "urgent"


def test_incomplete_coverage_alerts_even_without_findings() -> None:
    messages = plan_code_security_notifications(_package(complete=False, issues=()), routes=_ROUTES)
    assert [m.template_key for m in messages] == [
        "code_security_coverage_alert",
        "code_security_digest",
    ]


def test_clean_complete_scan_sends_nothing() -> None:
    assert plan_code_security_notifications(_package(issues=()), routes=_ROUTES) == ()


def test_missing_route_fails_closed_instead_of_falling_back_to_approval() -> None:
    with pytest.raises(NotificationPlanError, match=DIGEST_CATEGORY):
        plan_code_security_notifications(_package(), routes={ALERT_CATEGORY, "hil_approval"})


def test_templates_render_in_korean() -> None:
    (digest,) = plan_code_security_notifications(_package(), routes=_ROUTES)
    title, _ = NotificationCatalog.load_default().render(
        digest.template_key or "", digest.params, "ko"
    )
    assert title.startswith("코드 보안 요약")
