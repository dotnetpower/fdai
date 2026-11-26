"""Provider-schema deployment evidence validation."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_deployment_cli.github_workflow_values import (
    _DIGEST,
    _OCI_DIGEST,
    _PROVIDER_SOURCE_REVISION,
)


def _validate_provider_schema_core_baseline(
    value: Mapping[str, object],
    *,
    expected_source_revision: str,
    expected_image_digest: str,
) -> None:
    """Reject a provider baseline that does not prove the exact healthy Core image."""

    max_inactive_revisions = value.get("max_inactive_revisions")
    if (
        set(value)
        != {
            "schema_version",
            "source_revision",
            "image_digest",
            "core_app_ref_digest",
            "active_revision_ref_digest",
            "max_inactive_revisions",
            "health_state",
            "provisioning_state",
            "observed_at",
            "grants_authority",
        }
        or value.get("schema_version") != "fdai.provider-schema-core-baseline.v1"
        or value.get("source_revision") != expected_source_revision
        or value.get("image_digest") != expected_image_digest
        or value.get("health_state") != "Healthy"
        or value.get("provisioning_state") != "Provisioned"
        or value.get("grants_authority") is not False
        or not isinstance(max_inactive_revisions, int)
        or isinstance(max_inactive_revisions, bool)
        or max_inactive_revisions < 1
        or not isinstance(value.get("observed_at"), str)
    ):
        raise ValueError("github_provider_schema_core_baseline_invalid")
    for field in ("core_app_ref_digest", "active_revision_ref_digest"):
        digest = value.get(field)
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ValueError("github_provider_schema_core_baseline_invalid")


def _validate_provider_schema_evidence(
    value: Mapping[str, object],
    *,
    expected_application_source: str,
    expected_runtime_revision: str,
    expected_plan_id: str,
) -> dict[str, object]:
    """Validate durable provider generation and conditional agent-review evidence."""

    expected_fields = {
        "schema_version",
        "application_source_commit",
        "runtime_image_revision",
        "plan_id",
        "job_execution_ref_digest",
        "job_execution_status",
        "checked_at",
        "provider_source_revision",
        "baseline_digest",
        "observed_digest",
        "drift_digest",
        "disposition",
        "durable_generation_digest",
        "durable_generation_revision",
        "run_receipt_digest",
        "review_package_digest",
        "heimdall_review_dispatched",
        "review_evidence_status",
        "correlation_id",
        "forseti_risk_verdict",
        "forseti_reason",
        "saga_audit_entry_hash",
        "grants_authority",
    }
    generation_revision = value.get("durable_generation_revision")
    if (
        set(value) != expected_fields
        or value.get("schema_version") != "fdai.provider-schema-deployment-evidence.v1"
        or value.get("application_source_commit") != expected_application_source
        or value.get("runtime_image_revision") != expected_runtime_revision
        or value.get("plan_id") != expected_plan_id
        or value.get("job_execution_status") != "Succeeded"
        or value.get("grants_authority") is not False
        or not isinstance(value.get("checked_at"), str)
        or value.get("disposition") not in {"unchanged", "compatible", "breaking"}
        or not isinstance(generation_revision, int)
        or isinstance(generation_revision, bool)
        or generation_revision < 1
    ):
        raise ValueError("github_provider_schema_evidence_invalid")
    job_execution_digest = value.get("job_execution_ref_digest")
    if not isinstance(job_execution_digest, str) or _DIGEST.fullmatch(job_execution_digest) is None:
        raise ValueError("github_provider_schema_evidence_invalid")
    drift_digest = value.get("drift_digest")
    if drift_digest is not None and (
        not isinstance(drift_digest, str) or _DIGEST.fullmatch(drift_digest) is None
    ):
        raise ValueError("github_provider_schema_evidence_invalid")
    provider_revision = value.get("provider_source_revision")
    if (
        not isinstance(provider_revision, str)
        or _PROVIDER_SOURCE_REVISION.fullmatch(provider_revision) is None
    ):
        raise ValueError("github_provider_schema_evidence_invalid")
    for field in (
        "baseline_digest",
        "observed_digest",
        "durable_generation_digest",
        "run_receipt_digest",
    ):
        digest = value.get(field)
        if not isinstance(digest, str) or _OCI_DIGEST.fullmatch(digest) is None:
            raise ValueError("github_provider_schema_evidence_invalid")
    review_status = value.get("review_evidence_status")
    if review_status == "verified":
        if (
            value.get("disposition") != "breaking"
            or value.get("heimdall_review_dispatched") is not True
            or not isinstance(drift_digest, str)
            or _DIGEST.fullmatch(drift_digest) is None
            or value.get("correlation_id") != f"provider-schema:azure:{drift_digest}"
            or value.get("forseti_risk_verdict") != "hil"
            or value.get("forseti_reason") != "no_rule_match"
            or not isinstance(value.get("review_package_digest"), str)
            or _OCI_DIGEST.fullmatch(str(value["review_package_digest"])) is None
            or not isinstance(value.get("saga_audit_entry_hash"), str)
        ):
            raise ValueError("github_provider_schema_evidence_invalid")
    elif review_status == "not_applicable":
        if (
            value.get("disposition") == "breaking"
            or value.get("heimdall_review_dispatched") is not False
            or any(
                value.get(field) is not None
                for field in (
                    "review_package_digest",
                    "correlation_id",
                    "forseti_risk_verdict",
                    "forseti_reason",
                    "saga_audit_entry_hash",
                )
            )
        ):
            raise ValueError("github_provider_schema_evidence_invalid")
    else:
        raise ValueError("github_provider_schema_evidence_invalid")
    return {
        "provider_source_revision": provider_revision,
        "durable_generation_digest": value["durable_generation_digest"],
        "durable_generation_revision": value["durable_generation_revision"],
        "disposition": value["disposition"],
        "review_evidence_status": review_status,
        "heimdall_review_dispatched": value["heimdall_review_dispatched"],
        "forseti_risk_verdict": value["forseti_risk_verdict"],
        "saga_audit_entry_hash": value["saga_audit_entry_hash"],
    }
