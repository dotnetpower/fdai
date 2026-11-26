"""Checks adapter uses mock HTTP only and never publishes raw probe data."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fdai.core.deploy_preflight.report import DeploymentReadinessReport, ReadinessVerdict
from fdai.delivery.github.preflight_checks import (
    GitHubPreflightCheckPublisher,
    GitHubPreflightChecksConfig,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.preflight_check import PreflightCheck, PreflightCheckPublishError

_SHA = "a" * 40


def _check(
    *,
    mode: Mode = Mode.SHADOW,
    severity: FindingSeverity | None = None,
    pr_ref: str = "example/iac#42",
) -> PreflightCheck:
    findings = (
        (
            ProbeFinding(
                id="private-finding-id",
                category=ProbeCategory.SECRET_CONFIG,
                severity=severity,
                title="private-finding-title",
                evidence=ProbeEvidence(
                    source="private-source", detail="private-sensitive-evidence"
                ),
                resolution=ProbeResolution(kind=ResolutionKind.MANUAL),
            ),
        )
        if severity is not None
        else ()
    )
    return PreflightCheck(
        pr_ref=pr_ref,
        check_key="preflight-run-1",
        metadata={"private-metadata": "private-credential-value"},
        report=DeploymentReadinessReport(
            scope="private-scope",
            generated_at="2026-09-26T00:00:00+00:00",
            mode=mode,
            verdict=(
                ReadinessVerdict.BLOCKED
                if severity is FindingSeverity.BLOCKING
                else ReadinessVerdict.NEEDS_REVIEW
                if findings
                else ReadinessVerdict.CLEAR
            ),
            findings=findings,
            checked_categories=(ProbeCategory.SECRET_CONFIG,),
        ),
    )


class _GitHub:
    def __init__(self, *, head: str = _SHA, fail: int = 0) -> None:
        self.head = head
        self.fail = fail
        self.requests: list[httpx.Request] = []
        self.posted: dict[str, Any] | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(self.fail, text="private-credential-value")
        if request.url.path.endswith("/pulls/42"):
            return httpx.Response(200, json={"head": {"sha": self.head}})
        if request.url.path.endswith("/check-runs") and request.method == "GET":
            if self.posted is not None and self.posted["head_sha"] == self.head:
                return httpx.Response(
                    200,
                    json={
                        "total_count": 1,
                        "check_runs": [
                            {
                                "id": 77,
                                "head_sha": self.head,
                                "external_id": self.posted["external_id"],
                                "status": "completed",
                                "conclusion": self.posted["conclusion"],
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"total_count": 0, "check_runs": []})
        if request.url.path.endswith("/check-runs") and request.method == "POST":
            self.posted = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 77,
                    "head_sha": self.head,
                    "external_id": self.posted["external_id"],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")


def _publisher(github: _GitHub, *, token_provider: Any = None) -> GitHubPreflightCheckPublisher:
    async def token() -> str:
        return "test-token"

    return GitHubPreflightCheckPublisher(
        config=GitHubPreflightChecksConfig(owner="example", repo="iac"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(github.handle)),
        token_provider=token_provider or token,
    )


@pytest.mark.parametrize(
    "base", ["http://example.com", "https://user:pass@example.com", "https://example.com?key=1"]
)
def test_rejects_insecure_or_credential_bearing_api_base(base: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        GitHubPreflightChecksConfig(owner="example", repo="iac", api_base=base)


@pytest.mark.parametrize(
    ("mode", "severity", "conclusion"),
    [
        (Mode.SHADOW, FindingSeverity.BLOCKING, "neutral"),
        (Mode.ENFORCE, FindingSeverity.BLOCKING, "failure"),
        (Mode.ENFORCE, FindingSeverity.WARNING, "action_required"),
        (Mode.ENFORCE, None, "success"),
    ],
)
async def test_conclusion_is_sanitized_and_mode_aware(
    mode: Mode, severity: FindingSeverity | None, conclusion: str
) -> None:
    github = _GitHub()
    receipt = await _publisher(github).publish(_check(mode=mode, severity=severity))
    assert receipt.check_ref == "github-check:77"
    assert receipt.already_existed is False
    assert receipt.url is None
    assert github.posted is not None
    assert github.posted["conclusion"] == conclusion
    assert github.posted["status"] == "completed"
    assert github.posted["head_sha"] == _SHA
    assert "private-" not in json.dumps(github.posted)
    assert all("private-" not in request.url.path for request in github.requests)


async def test_redelivery_is_idempotent_on_exact_pr_head_but_new_head_gets_new_check() -> None:
    github = _GitHub()
    publisher = _publisher(github)
    check = _check()
    first, second = await asyncio.gather(publisher.publish(check), publisher.publish(check))
    assert first.already_existed is False
    assert second.already_existed is True
    assert len([request for request in github.requests if request.method == "POST"]) == 1
    github.head = "b" * 40
    newer = await publisher.publish(check)
    assert newer.already_existed is False
    assert len([request for request in github.requests if request.method == "POST"]) == 2


async def test_same_key_with_changed_report_is_not_mistaken_for_previous_check() -> None:
    github = _GitHub()
    publisher = _publisher(github)
    await publisher.publish(_check())
    with pytest.raises(PreflightCheckPublishError, match="state is unavailable"):
        await publisher.publish(_check(severity=FindingSeverity.WARNING))
    assert len([request for request in github.requests if request.method == "POST"]) == 1


async def test_invalid_pr_reference_reaches_no_adapter_transport() -> None:
    github = _GitHub()
    with pytest.raises(PreflightCheckPublishError, match="reference"):
        await _publisher(github).publish(_check(pr_ref="elsewhere/repo#42"))
    assert github.requests == []


@pytest.mark.parametrize("failure", [401, 429, 503])
async def test_provider_failure_exposes_no_response_body_or_token(failure: int) -> None:
    github = _GitHub(fail=failure)
    with pytest.raises(PreflightCheckPublishError) as error:
        await _publisher(github).publish(_check())
    assert str(error.value) == "preflight Checks adapter unavailable"
    assert "private-" not in str(error.value)
    assert len(github.requests) == 1


async def test_unavailable_token_does_not_send_a_request() -> None:
    github = _GitHub()

    async def unavailable() -> str:
        raise ValueError("private-credential-value")

    with pytest.raises(PreflightCheckPublishError) as error:
        await _publisher(github, token_provider=unavailable).publish(_check())
    assert "private-" not in str(error.value)
    assert github.requests == []


async def test_inconsistent_report_is_not_published_as_a_success() -> None:
    github = _GitHub()
    check = _check(mode=Mode.ENFORCE, severity=FindingSeverity.BLOCKING)
    from dataclasses import replace

    check = replace(check, report=replace(check.report, verdict=ReadinessVerdict.CLEAR))
    with pytest.raises(PreflightCheckPublishError, match="inconsistent"):
        await _publisher(github).publish(check)
    assert github.requests == []


async def test_missing_head_or_ambiguous_previous_check_fails_closed() -> None:
    github = _GitHub(head="invalid-head")
    with pytest.raises(PreflightCheckPublishError, match="head revision"):
        await _publisher(github).publish(_check())
    assert all(request.method == "GET" for request in github.requests)
