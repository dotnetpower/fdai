"""Tests for the read-only code-security review projection."""

from __future__ import annotations

from typing import Any

from fdai_operator_service.code_security_review_projection import (
    GAP_MALFORMED,
    GAP_PACK_MALFORMED,
    GAP_TRUNCATED,
    code_security_packs_projection,
    code_security_reviews_projection,
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
