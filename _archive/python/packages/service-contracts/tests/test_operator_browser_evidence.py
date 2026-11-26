from datetime import UTC, datetime

import pytest
from fdai_service_contracts import BrowserEvidenceWorkspaceQuery


def test_workspace_query_accepts_exact_bounded_filters() -> None:
    query = BrowserEvidenceWorkspaceQuery(
        limit=50,
        artifact_id=f"sha256:{'a' * 64}",
        host="dashboard.example",
        host_scope="requested",
        policy_id="dashboard",
        policy_version=4,
        captured_from=datetime(2026, 9, 1, tzinfo=UTC),
        captured_before=datetime(2026, 9, 15, tzinfo=UTC),
        retention="expiring",
        finding="present",
        custody_ref="00000000-0000-0000-0000-000000000001",
        sort="newest",
    )

    assert query.host == "dashboard.example"
    assert query.policy_version == 4


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("limit", True, "limit"),
        ("limit", 0, "limit"),
        ("artifact_id", "sha256:not-a-digest", "SHA-256"),
        ("host", "Dashboard.Example", "lowercase IDNA"),
        ("host_scope", "all", "host scope"),
        ("policy_id", " ", "policy id"),
        ("policy_id", "대시보드", "ASCII"),
        ("policy_version", 0, "policy version"),
        ("policy_version", 2_147_483_648, "policy version"),
        ("retention", "expired", "retention"),
        ("finding", "unknown", "finding"),
        ("custody_ref", "\n", "custody"),
        ("custody_ref", "\N{NO-BREAK SPACE}custody", "ASCII"),
        ("sort", "expiry", "sort"),
        ("cursor", "not+padded", "base64url"),
    ),
)
def test_workspace_query_rejects_malformed_filters(field: str, value: object, message: str) -> None:
    arguments: dict[str, object] = {"limit": 25, field: value}
    if field == "policy_version":
        arguments["policy_id"] = "dashboard"

    with pytest.raises(ValueError, match=message):
        BrowserEvidenceWorkspaceQuery(**arguments)  # type: ignore[arg-type]


def test_workspace_query_requires_ordered_aware_capture_bounds() -> None:
    with pytest.raises(ValueError, match="timezone"):
        BrowserEvidenceWorkspaceQuery(
            limit=25,
            captured_from=datetime(2026, 9, 1),
        )
    with pytest.raises(ValueError, match="reversed"):
        BrowserEvidenceWorkspaceQuery(
            limit=25,
            captured_from=datetime(2026, 9, 2, tzinfo=UTC),
            captured_before=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_workspace_query_requires_policy_id_for_version() -> None:
    with pytest.raises(ValueError, match="include policy id"):
        BrowserEvidenceWorkspaceQuery(limit=25, policy_version=4)
