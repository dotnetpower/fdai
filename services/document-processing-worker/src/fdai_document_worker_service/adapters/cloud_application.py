"""Current prior-authority checks, including the final visibility transaction fence."""

from __future__ import annotations

from typing import Any

import psycopg
from fdai_service_contracts import DocumentVersion
from fdai_service_contracts.cloud_knowledge_application import (
    CloudApplicationRequest,
    CloudApplicationUnavailableError,
    CloudPolicyAuthority,
    validate_application_version,
)

APPLICATION_SQL = (
    "SELECT a.payload AS application, p.payload AS authority, clock_timestamp() AS observed_at, "
    "v.active AS candidate_active, (SELECT current.version_id FROM document_version current "
    " WHERE current.document_id = v.document_id AND current.active) AS active_version_id "
    "FROM document_knowledge_application a "
    "JOIN document_knowledge_policy p ON p.digest = a.policy_digest "
    "JOIN document_version v ON v.upload_id = a.upload_id "
    "WHERE a.upload_id = %s"
)


def check_application_row(row: dict[str, Any] | None, version: DocumentVersion) -> None:
    if row is None:
        raise CloudApplicationUnavailableError("application prior authority is unavailable")
    try:
        request = CloudApplicationRequest.model_validate(row["application"])
        expected = (
            version.version_id if row["candidate_active"] else request.expected_active_version_id
        )
        if row["active_version_id"] != expected:
            raise ValueError("application active generation changed")
        validate_application_version(
            CloudPolicyAuthority.model_validate(row["authority"]),
            request,
            version,
            row["observed_at"],
        )
    except ValueError:
        raise CloudApplicationUnavailableError("application prior authority changed") from None


async def fence_application(
    connection: psycopg.AsyncConnection[dict[str, Any]], version: DocumentVersion
) -> None:
    """Serialize visibility with policy review/revocation without granting the worker writes."""
    binding = version.cloud_knowledge
    if binding is None or binding.application is None:
        return
    await connection.execute(
        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
        (f"cloud-policy:{binding.application.policy_digest}",),
    )
    row = await (await connection.execute(APPLICATION_SQL, (version.upload_id,))).fetchone()
    check_application_row(row, version)
