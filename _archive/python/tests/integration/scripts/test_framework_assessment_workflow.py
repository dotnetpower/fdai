"""Static contracts for the governed framework shadow assessment workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.deployment.azure import export_wara_database_context as exporter

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/framework-assessment-shadow.yml").read_text(encoding="utf-8")


def test_workflow_is_exact_revision_read_only_and_evidence_bounded() -> None:
    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in WORKFLOW
    assert "environment: plan-only" in WORKFLOW
    assert "Verify required CI for exact revision" in WORKFLOW
    assert 'select(.name == "required")' in WORKFLOW
    assert "login-deploy-identity.sh" in WORKFLOW
    assert "fdai.delivery.framework_assessment_cli" in WORKFLOW
    assert "export_wara_database_context.py" in WORKFLOW
    assert "az containerapp job list" not in WORKFLOW
    assert "framework-assessment-receipt.json" in WORKFLOW
    assert "retention-days: 90" in WORKFLOW
    assert "terraform apply" not in WORKFLOW
    assert "az deployment" not in WORKFLOW


def test_exporter_selects_one_topology_bound_workload() -> None:
    assert exporter.select_wara_workload_id([{"id": "workload-example"}]) == "workload-example"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([], "found 0"),
        ([{"id": "one"}, {"id": "two"}], "found at least 2"),
        ([{"id": ""}], "id is invalid"),
        ([{"id": " workload"}], "id is invalid"),
        ([{"id": 1}], "id is invalid"),
    ],
)
def test_exporter_rejects_missing_ambiguous_or_invalid_workload_scope(
    rows: list[dict[str, object]],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        exporter.select_wara_workload_id(rows)


def test_exporter_discovers_with_bounded_read_only_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(
            self,
            statement: str,
            params: object | None = None,
        ) -> Connection:
            self.calls.append((statement, params))
            return self

        def fetchall(self) -> list[dict[str, object]]:
            return [{"id": "workload-example"}]

    connection = Connection()

    def connect(dsn: str, **kwargs: object) -> Connection:
        assert dsn == "postgresql://example"
        assert kwargs["connect_timeout"] == 10
        return connection

    monkeypatch.setattr(exporter.psycopg, "connect", connect)

    assert exporter.discover_wara_workload_id("postgresql://example") == "workload-example"
    assert connection.calls[0] == ("SET TRANSACTION READ ONLY", None)
    assert connection.calls[1][0] == "SELECT set_config('statement_timeout', %s, true)"
    assert "resource.object_type='Workload'" in connection.calls[2][0]
    assert "link.link_type='workload_runs_on'" in connection.calls[2][0]
    assert connection.calls[2][0].endswith("ORDER BY resource.id LIMIT 2")
