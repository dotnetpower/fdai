"""Contract checks for the Browser evidence workspace read boundary."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = (
    _REPO_ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260915_operator_browser_evidence_workspace.py"
)


def test_workspace_migration_is_additive_and_read_only() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))

    assert migration["down_revision"] == "operator_handover_admission_20260914"
    assert migration["migration_owner"] == "operator-service"
    assert migration["owned_tables"] == ()
    assert "SECURITY DEFINER" not in source
    assert "EXECUTE" not in source
    assert "CREATE VIEW operator_browser_evidence_workspace" in source
    assert "CREATE VIEW operator_browser_evidence_workspace_summary" in source
    assert "GRANT SELECT" in source
    assert "GRANT INSERT" not in source
    assert "GRANT UPDATE" not in source
    assert "GRANT DELETE" not in source
    assert "length(source_host) BETWEEN 1 AND 253" in source
    assert "length(final_host) BETWEEN 1 AND 253" in source
    assert "OCTET_LENGTH(source_host) = length(source_host)" in source
    assert "^[^.]{1,63}([.][^.]{1,63})*[.]?$" in source
    assert "OCTET_LENGTH(policy_id) = length(policy_id)" in source
    assert "OCTET_LENGTH(browser_version) = length(browser_version)" in source
    assert (
        "chain_of_custody_audit_ref\n"
        "                       = BTRIM(chain_of_custody_audit_ref)" in source
    )
    assert "legal_hold_ref = BTRIM(legal_hold_ref)" in source
    assert "OCTET_LENGTH(legal_hold_ref)" in source
    assert "END AS custody_audit_uuid" in source


def test_workspace_view_exposes_no_payload_or_withheld_identity() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    workspace = source.split("CREATE VIEW operator_browser_evidence_workspace\n", 1)[1].split(
        "CREATE VIEW operator_browser_evidence_workspace_summary", 1
    )[0]
    summary = source.split("CREATE VIEW operator_browser_evidence_workspace_summary\n", 1)[1].split(
        "REVOKE ALL PRIVILEGES", 1
    )[0]

    for forbidden in (
        "screenshot BYTEA",
        "visible_text",
        "aria_snapshot",
        "redaction_manifest",
        "prompt_injection_findings",
        "isolation ",
    ):
        assert forbidden not in workspace
    for identity in (
        "artifact_id",
        "source_host",
        "final_host",
        "policy_id",
        "chain_of_custody_audit_ref",
        "captured_at",
        "expires_at",
    ):
        assert identity not in summary
    assert (
        "REVOKE ALL PRIVILEGES\n"
        "          ON TABLE operator_browser_evidence_admission_internal\n"
        "        FROM PUBLIC, fdai_operator" in source
    )


def test_workspace_downgrade_preserves_v1_and_durable_artifacts() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", 1)[1]

    assert "DROP VIEW operator_browser_evidence_workspace_summary" in downgrade
    assert "DROP VIEW operator_browser_evidence_workspace" in downgrade
    assert "DROP VIEW operator_browser_evidence_admission_internal" in downgrade
    assert "DROP VIEW operator_browser_evidence_metadata" not in downgrade
    assert "DROP TABLE browser_evidence_artifact" not in downgrade
