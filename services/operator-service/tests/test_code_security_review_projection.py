"""Tests for the read-only code-security review projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai_operator_service.code_security_issue_projection import code_security_issues_projection
from fdai_operator_service.code_security_review_projection import (
    GAP_MALFORMED,
    GAP_PACK_MALFORMED,
    GAP_TRUNCATED,
    code_security_packs_projection,
    code_security_repositories_projection,
    code_security_reviews_projection,
    code_security_scan_requests_projection,
    code_security_worker_status_projection,
    read_code_security_projection,
)
from fdai_operator_service.families.operations import ProjectionQuery
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import OperatorRole

_REVISION = "a" * 40


def _package(**overrides: object) -> dict[str, object]:
    package: dict[str, object] = {
        "schema_version": "1.0.0",
        "kind": "code-security-review",
        "repository_alias": "example-service",
        "revision": _REVISION,
        "review_digest": "4" * 64,
        "issue_count": 2,
        "by_priority": {"P0": 1, "P1": 1, "P2": 0, "P3": 0, "P4": 0},
        "by_severity": {"critical": 1, "high": 0, "medium": 0, "low": 0, "undetermined": 1},
        "by_confidence": {
            "hypothesis": 0,
            "reported": 1,
            "corroborated": 0,
            "verified": 1,
            "proven": 0,
        },
        "known_exploited_count": 0,
        "exposure": "exposed",
        "coverage_complete": True,
        "top_issue_ids": ["FDAI-SEC-0123456789ab", "FDAI-SEC-ba9876543210"],
        "review_required": True,
        "grants_authority": False,
    }
    package.update(overrides)
    return package


def _row(
    package: dict[str, object], recorded_at: str = "2026-10-07T00:00:00+00:00"
) -> dict[str, Any]:
    alias, revision = package["repository_alias"], package["revision"]
    return {
        "key": f"runtime:code-security-review:{alias}:{revision}",
        "value": {"package": package, "recorded_at": recorded_at},
    }


def test_valid_rows_render_newest_first_with_decision() -> None:
    older = _row(_package(), "2026-10-06T00:00:00+00:00")
    newer = _row(
        _package(
            revision="b" * 40,
            issue_count=0,
            by_priority={"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0},
        )
    )
    result = code_security_reviews_projection([older, newer])
    assert result["available"] is True and result["complete"] is True
    reviews = result["reviews"]
    assert isinstance(reviews, list)
    assert [item["revision"] for item in reviews] == ["b" * 40, _REVISION]
    assert reviews[0]["decision"] == "clear"
    assert reviews[1]["decision"] == "urgent"
    assert reviews[1]["by_confidence"]["verified"] == 1


def test_incomplete_coverage_is_never_rendered_as_clear() -> None:
    row = _row(_package(issue_count=0, coverage_complete=False))
    (review,) = code_security_reviews_projection([row])["reviews"]  # type: ignore[misc]
    assert review["decision"] == "coverage_incomplete"


def test_malformed_or_leaking_rows_become_gaps() -> None:
    mismatched = _row(_package())
    mismatched["key"] = "runtime:code-security-review:other:" + _REVISION
    rows = [
        mismatched,
        _row(_package(grants_authority=True)),
        _row(_package(top_issue_ids=["src/app.py:12"])),
        _row(_package(by_priority={"P0": 1})),
        _row(_package(coverage_complete="yes")),
        {"key": "runtime:code-security-review:x", "value": "not-a-mapping"},
        _row(_package(), "yesterday"),
    ]
    result = code_security_reviews_projection(rows)
    assert result["available"] is False and result["complete"] is False
    assert result["reviews"] == []
    assert [gap["reason_code"] for gap in result["gaps"]] == [GAP_MALFORMED] * len(rows)  # type: ignore[union-attr]


def test_truncation_is_reported() -> None:
    rows = [_row(_package(revision=f"{index:040x}")) for index in range(201)]
    result = code_security_reviews_projection(rows)
    assert len(result["reviews"]) == 200  # type: ignore[arg-type]
    assert result["gaps"] == [{"reason_code": GAP_TRUNCATED}]


async def test_reader_serves_code_security_reviews_from_state_kv(monkeypatch: Any) -> None:
    statements: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(
        self: RuntimeProjectionReader, statement: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        del self
        statements.append((statement, parameters))
        return [_row(_package())]

    class _Fallback:
        async def read(self, query: ProjectionQuery) -> dict[str, object]:
            raise AssertionError(f"unexpected fallback for {query.operation}")

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        _Fallback(),  # type: ignore[arg-type]
    )
    result = await reader.read(
        ProjectionQuery(
            operation="code_security.reviews",
            principal_id="operator-a",
            path={},
            params={},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        )
    )
    assert statements[0][1] == ("runtime:code-security-review:%",)
    assert "LIMIT 201" in statements[0][0]
    assert result["available"] is True


def _pack_row(**overrides: object) -> dict[str, Any]:
    value: dict[str, object] = {
        "pack_id": "0123456789ab",
        "manifest_sha256": "1" * 64,
        "base_commit": _REVISION,
        "issue_ids": ["FDAI-SEC-0123456789ab", "FDAI-SEC-ba9876543210"],
        "expires_at": "2026-10-14T00:00:00+00:00",
        "revoked": False,
        "recorded_at": "2026-10-07T00:00:00+00:00",
        "revision": 3,
        "reviews": [
            {
                "kind": "fix_verification",
                "rescan_revision": "b" * 40,
                "recorded_at": "2026-10-08T00:00:00+00:00",
                "verdicts": [
                    {
                        "issue_id": "FDAI-SEC-0123456789ab",
                        "claim": "fixed_claimed",
                        "verdict": "fixed_verified",
                        "reasons": [],
                    },
                    {
                        "issue_id": "FDAI-SEC-ba9876543210",
                        "claim": "fixed_claimed",
                        "verdict": "still_present",
                        "reasons": ["rescan still reports the root cause"],
                    },
                ],
            },
            {
                "kind": "false_positive_adjudication",
                "issue_id": "FDAI-SEC-ba9876543210",
                "decision": "accepted",
                "issue_disposition": "false_positive",
                "claimant": "dev@example.com",
                "adjudicator": "lead@example.com",
                "approval_ref": "APPROVAL-1",
                "rationale": "free text that must not reach the Console",
                "single_operator_profile": False,
                "decided_at": "2026-10-08T01:00:00+00:00",
                "recorded_at": "2026-10-08T01:00:00+00:00",
            },
        ],
    }
    value.update(overrides)
    return {"key": f"runtime:code-security-pack:{value['pack_id']}", "value": value}


def test_pack_projection_summarizes_verdicts_and_adjudications_without_free_text() -> None:
    result = code_security_packs_projection([_pack_row()])
    assert result["available"] is True and result["complete"] is True
    (pack,) = result["packs"]  # type: ignore[misc]
    assert pack["issue_count"] == 2
    assert pack["latest_verification"]["verdicts"] == {
        "fixed_verified": 1,
        "still_present": 1,
        "inconclusive": 0,
        "not_applicable": 0,
    }
    (adjudication,) = pack["adjudications"]
    assert adjudication["issue_disposition"] == "false_positive"
    rendered = repr(result)
    assert "free text" not in rendered and "rescan still reports" not in rendered
    assert "manifest_sha256" not in rendered and "approval_ref" not in rendered


def test_malformed_pack_rows_become_gaps() -> None:
    rows = [
        _pack_row(pack_id="../escape"),
        _pack_row(revoked="no"),
        _pack_row(reviews=[{"kind": "unknown"}]),
        _pack_row(reviews=[{"kind": "fix_verification", "verdicts": [{"verdict": "fixed"}]}]),
        {"key": "runtime:code-security-pack:ffffffffffff", "value": _pack_row()["value"]},
    ]
    result = code_security_packs_projection(rows)
    assert result["packs"] == [] and result["available"] is False
    assert [gap["reason_code"] for gap in result["gaps"]] == [GAP_PACK_MALFORMED] * len(rows)  # type: ignore[union-attr]


def test_sourced_reviews_render_source_and_producers() -> None:
    row = _row(_package())
    package = row["value"]["package"]
    package["schema_version"] = "1.1.0"
    package["source"] = {
        "kind": "external_sarif",
        "provider": "mdash",
        "revision_kind": "commit",
        "trigger": "cli",
        "request_id": None,
    }
    package["producers"] = ["MDASH"]
    (review,) = code_security_reviews_projection([row])["reviews"]  # type: ignore[misc]
    assert review["source"]["provider"] == "mdash"
    assert review["producers"] == ["MDASH"]
    (legacy,) = code_security_reviews_projection([_row(_package())])["reviews"]  # type: ignore[misc]
    assert legacy["source"] is None and legacy["producers"] == []
    package["source"] = {**package["source"], "kind": "ftp"}
    assert code_security_reviews_projection([row])["gaps"] == [
        {"reason_code": "code_security_review_malformed"}
    ]


def _repository_row(alias: str = "example-app", **overrides: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": "code-security-repository",
        "schema_version": "1.0.0",
        "repository_alias": alias,
        "provider": "github",
        "location": "example/app",
        "default_ref": "main",
        "exposure": "exposed",
        "enabled": True,
        "registered_at": "2026-10-08T00:00:00+00:00",
        "registered_by": "owner@example.com",
        "revision": 1,
    }
    value.update(overrides)
    return {"key": f"runtime:code-security-repository:{alias}", "value": value}


def test_repositories_render_without_registrant_identity() -> None:
    result = code_security_repositories_projection(
        [_repository_row("b-app"), _repository_row("a-app"), _repository_row("c", provider="x")]
    )
    assert [item["repository_alias"] for item in result["repositories"]] == ["a-app", "b-app"]  # type: ignore[index, union-attr]
    assert "owner@example.com" not in str(result)
    assert result["gaps"] == [{"reason_code": "code_security_repository_malformed"}]


def _request_row(status: str, **extra: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": "operator.proposal",
        "operation": "code_security.scan_request",
        "proposal_id": "operator-" + "a" * 32,
        "principal_id": "contributor-oid",
        "dispatch_status": status,
        "accepted_at": "2026-10-08T01:00:00+00:00",
        "payload": {"payload": {"repository_alias": "example-app", "ref": "main"}},
    }
    value.update(extra)
    return {"key": "operator-proposal:operations:" + "b" * 64, "value": value}


def test_scan_requests_render_status_and_bounded_result() -> None:
    completed = _request_row(
        "published",
        closed_at="2026-10-08T01:05:00+00:00",
        request_result={
            "revision": _REVISION,
            "review_digest": "4" * 64,
            "decision": "open",
            "issue_count": 3,
            "coverage_complete": True,
            "published": False,
        },
    )
    rejected = _request_row(
        "rejected",
        closed_at="2026-10-08T01:02:00+00:00",
        rejection_reason="repository_disabled",
    )
    result = code_security_scan_requests_projection(
        [
            _request_row("pending"),
            _request_row("claimed"),
            completed,
            rejected,
            _request_row("rejected", closed_at="2026-10-08T01:02:00+00:00", rejection_reason="x"),
        ]
    )
    statuses = sorted(item["status"] for item in result["requests"])  # type: ignore[index, union-attr]
    assert statuses == ["completed", "queued", "rejected", "running"]
    assert "contributor-oid" not in str(result)
    done = next(item for item in result["requests"] if item["status"] == "completed")  # type: ignore[union-attr]
    assert done["result"]["issue_count"] == 3
    assert result["gaps"] == [{"reason_code": "code_security_scan_request_malformed"}]


async def test_reader_serves_scan_requests_by_operation(monkeypatch: Any) -> None:
    statements: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_all(sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        statements.append((sql, params))
        return []

    result = await read_code_security_projection("code_security.scan_requests", fetch_all)
    assert result["requests"] == []
    assert statements[0][1] == ("code_security.scan_request", "code_security.repository_change")
    assert "operator-proposal:operations:%%" in statements[0][0]
    await read_code_security_projection("code_security.repositories", fetch_all)
    assert statements[1][1] == ("runtime:code-security-repository:%",)


def test_repository_changes_render_beside_scan_requests() -> None:
    change = _request_row(
        "published",
        operation="code_security.repository_change",
        closed_at="2026-10-08T01:05:00+00:00",
        request_result={"action": "register", "repository_alias": "example-app", "enabled": True},
        payload={
            "payload": {
                "action": "register",
                "repository_alias": "example-app",
                "location": "example/app",
            }
        },
    )
    rejected = _request_row(
        "rejected",
        operation="code_security.repository_change",
        closed_at="2026-10-08T01:05:00+00:00",
        rejection_reason="repository_conflict",
        payload={"payload": {"action": "enable", "repository_alias": "example-app"}},
    )
    bad = _request_row(
        "pending",
        operation="code_security.repository_change",
        payload={"payload": {"action": "delete", "repository_alias": "example-app"}},
    )
    result = code_security_scan_requests_projection(
        [_request_row("pending"), change, rejected, bad]
    )
    kinds = sorted((item["kind"], item["status"]) for item in result["requests"])  # type: ignore[index, union-attr]
    assert kinds == [
        ("repository_change", "completed"),
        ("repository_change", "rejected"),
        ("scan", "queued"),
    ]
    registered = next(
        item
        for item in result["requests"]
        if item["status"] == "completed"  # type: ignore[union-attr]
    )
    assert registered["action"] == "register" and registered["location"] == "example/app"
    assert registered["result"] == {"enabled": True}
    assert result["gaps"] == [{"reason_code": "code_security_scan_request_malformed"}]


def test_repository_change_projects_automatic_initial_scan() -> None:
    change = _request_row(
        "published",
        operation="code_security.repository_change",
        closed_at="2026-10-08T01:05:00+00:00",
        request_result={
            "action": "register",
            "repository_alias": "example-app",
            "enabled": True,
            "initial_scan": {
                "status": "completed",
                "revision": _REVISION,
                "review_digest": "4" * 64,
                "decision": "clear",
                "issue_count": 0,
                "coverage_complete": True,
                "published": False,
            },
        },
        payload={
            "payload": {
                "action": "register",
                "repository_alias": "example-app",
                "location": "example/app",
            }
        },
    )
    result = code_security_scan_requests_projection([change])
    assert result["requests"][0]["result"]["initial_scan"] == {  # type: ignore[index]
        "status": "completed",
        "revision": _REVISION,
        "review_digest": "4" * 64,
        "decision": "clear",
        "issue_count": 0,
        "coverage_complete": True,
        "published": False,
    }


def _worker_row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "kind": "code-security-worker-status",
        "schema_version": "1.0.0",
        "state": "ready",
        "phase": "idle",
        "recorded_at": "2026-10-10T01:00:00+00:00",
        "request_interval_seconds": 5,
        "schedule_interval_seconds": 300,
        "next_request_at": "2026-10-10T01:00:05+00:00",
        "next_schedule_at": "2026-10-10T01:05:00+00:00",
        "request_processed": 1,
        "schedule_checked": 3,
        "schedule_scanned": 1,
        "schedule_unchanged": 2,
        "schedule_failed": 0,
    }
    value.update(overrides)
    return {"key": "runtime:code-security-worker:v1", "value": value}


def test_worker_status_projects_freshness_and_malformed_gaps() -> None:
    now = datetime(2026, 10, 10, 1, 0, 10, tzinfo=UTC)
    result = code_security_worker_status_projection([_worker_row()], now=now)
    assert result["available"] is True
    assert result["status"]["fresh"] is True  # type: ignore[index]
    stale = code_security_worker_status_projection([_worker_row()], now=now.replace(minute=2))
    assert stale["status"]["fresh"] is False  # type: ignore[index]
    malformed = code_security_worker_status_projection(
        [_worker_row(request_interval_seconds=0)], now=now
    )
    assert malformed["available"] is False
    assert malformed["gaps"] == [{"reason_code": "code_security_worker_status_malformed"}]
    overflow = code_security_worker_status_projection(
        [_worker_row(recorded_at="0001-01-01T00:00:00+14:00")], now=now
    )
    assert overflow["available"] is False
    assert overflow["gaps"] == [{"reason_code": "code_security_worker_status_malformed"}]


async def test_reader_serves_worker_status_by_operation() -> None:
    statements: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_all(sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        statements.append((sql, params))
        return []

    result = await read_code_security_projection("code_security.worker_status", fetch_all)
    assert result["available"] is False
    assert statements[0][1] == ("runtime:code-security-worker:v1",)


def _summary(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "issue_id": "FDAI-SEC-0123456789ab",
        "priority": "P1",
        "due_days": 7,
        "severity": "high",
        "confidence": "verified",
        "weakness_class": "command_injection",
        "cwe_ids": [78],
        "advisory_ids": [],
        "package": None,
        "producers": ["Opengrep"],
        "known_exploited": False,
    }
    value.update(overrides)
    return value


def test_issue_projection_requires_the_matching_review_digest() -> None:
    review = _row(_package())["value"]
    digest = review["package"]["review_digest"]
    ok = code_security_issues_projection(
        repository_alias="example-service",
        revision=_REVISION,
        review=review,
        issues_row={
            "review_digest": digest,
            "issues": [_summary(), _summary(path="src/x.py")],
            "truncated": True,
        },
        artifacts_row={
            "kind": "code-security-review-artifacts",
            "schema_version": "1.0.0",
            "repository_alias": "example-service",
            "revision": _REVISION,
            "review_digest": digest,
            "recorded_at": "2026-10-10T00:00:00+00:00",
            "html": "<!doctype html><title>report</title>",
            "sarif": (
                '{"version":"2.1.0","runs":[{"results":[{"properties":{'
                '"issue_id":"FDAI-SEC-0123456789ab","title":"Command injection",'
                '"severity_floor":"medium","severity_ceiling":"critical",'
                '"severity_rationale":"impact is bounded; attacker position is unknown",'
                '"deciding_facts":["attack_vector"]},"locations":[{"physicalLocation":{'
                '"artifactLocation":{"uri":"src/app.py"},"region":{"startLine":42}}}]}]}]}'
            ),
        },
    )
    assert ok["available"] is True and len(ok["issues"]) == 1  # type: ignore[arg-type]
    assert {gap["reason_code"] for gap in ok["gaps"]} == {  # type: ignore[union-attr]
        "code_security_issue_malformed",
        "code_security_issues_truncated",
    }
    assert ok["artifacts"] == {
        "mode": "full",
        "html": "<!doctype html><title>report</title>",
        "sarif": (
            '{"version":"2.1.0","runs":[{"results":[{"properties":{'
            '"issue_id":"FDAI-SEC-0123456789ab","title":"Command injection",'
            '"severity_floor":"medium","severity_ceiling":"critical",'
            '"severity_rationale":"impact is bounded; attacker position is unknown",'
            '"deciding_facts":["attack_vector"]},"locations":[{"physicalLocation":{'
            '"artifactLocation":{"uri":"src/app.py"},"region":{"startLine":42}}}]}]}]}'
        ),
    }
    issue = ok["issues"][0]  # type: ignore[index]
    assert issue["title"] == "Command injection"
    assert issue["severity_floor"] == "medium"
    assert issue["severity_ceiling"] == "critical"
    assert issue["location"] == {"path": "src/app.py", "start_line": 42}
    assert "src/x.py" not in str(ok)
    stale = code_security_issues_projection(
        repository_alias="example-service",
        revision=_REVISION,
        review=review,
        issues_row={"review_digest": "0" * 64, "issues": [_summary()], "truncated": False},
    )
    assert stale["available"] is False and stale["issues"] == []
    missing = code_security_issues_projection(
        repository_alias="example-service", revision=_REVISION, review=None, issues_row=None
    )
    assert missing["gaps"] == [{"reason_code": "code_security_issues_unavailable"}]


def test_missing_full_artifacts_fall_back_to_bounded_summary_views() -> None:
    review = _row(_package())["value"]
    result = code_security_issues_projection(
        repository_alias="example-service",
        revision=_REVISION,
        review=review,
        issues_row={
            "review_digest": review["package"]["review_digest"],
            "issues": [_summary()],
            "truncated": False,
        },
    )
    artifacts = result["artifacts"]
    assert artifacts["mode"] == "summary"  # type: ignore[index]
    assert "summary report" in artifacts["html"]  # type: ignore[index]
    assert '"version": "2.1.0"' in artifacts["sarif"]  # type: ignore[index]


async def test_reader_serves_issues_for_one_exact_review() -> None:
    import pytest

    review = _row(_package())["value"]
    statements: list[tuple[object, ...]] = []

    async def fetch_all(sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        statements.append(params)
        if str(params[0]).startswith("runtime:code-security-review:"):
            return [{"key": params[0], "value": review}]
        if str(params[0]).endswith(":artifacts"):
            return [
                {
                    "key": params[0],
                    "value": {
                        "kind": "code-security-review-artifacts",
                        "schema_version": "1.0.0",
                        "repository_alias": "example-service",
                        "revision": _REVISION,
                        "review_digest": review["package"]["review_digest"],
                        "recorded_at": "2026-10-10T00:00:00+00:00",
                        "html": "<!doctype html><title>report</title>",
                        "sarif": '{"version":"2.1.0","runs":[]}',
                    },
                }
            ]
        return [
            {
                "key": params[0],
                "value": {
                    "review_digest": review["package"]["review_digest"],
                    "issues": [_summary()],
                    "truncated": False,
                },
            }
        ]

    params = {"repository_alias": ("example-service",), "revision": (_REVISION,)}
    result = await read_code_security_projection("code_security.issues", fetch_all, params)
    assert result["available"] is True and len(result["issues"]) == 1  # type: ignore[arg-type]
    assert statements == [
        (f"runtime:code-security-review:example-service:{_REVISION}",),
        (f"runtime:code-security-issues:example-service:{_REVISION}",),
        (f"runtime:code-security-issues:example-service:{_REVISION}:artifacts",),
    ]
    with pytest.raises(ValueError, match="revision"):
        await read_code_security_projection(
            "code_security.issues", fetch_all, {"repository_alias": ("a",), "revision": ("x",)}
        )
