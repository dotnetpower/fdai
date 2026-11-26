"""Read-only Var source for previously reviewed reference-content authority."""

from uuid import UUID

import psycopg
from fdai_service_contracts import DocumentVersion
from fdai_service_contracts.cloud_knowledge_application import (
    CloudApplicationAuthorization,
    CloudApplicationRequest,
    CloudApplicationUnavailableError,
    CloudPolicyAuthority,
    validate_application_version,
)


class PostgresCloudApplicationAuthorization:
    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    async def authorize(
        self, *, document_id: str, upload_id: str, requester_id: str
    ) -> CloudApplicationAuthorization | None:
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
                await conn.set_read_only(True)
                await conn.execute("SET LOCAL statement_timeout = '5s'")
                row = await (
                    await conn.execute(
                        "SELECT v.payload, a.payload, p.payload, clock_timestamp(), "
                        "(SELECT current.version_id FROM document_version current "
                        "WHERE current.document_id = v.document_id AND current.active) "
                        "FROM document_version v "
                        "LEFT JOIN document_knowledge_application a ON a.upload_id = v.upload_id "
                        "LEFT JOIN document_knowledge_policy p ON p.digest = a.policy_digest "
                        "WHERE v.document_id = %s AND v.upload_id = %s",
                        (UUID(document_id), UUID(upload_id)),
                    )
                ).fetchone()
        except psycopg.Error as exc:
            raise CloudApplicationUnavailableError(
                "application authority source is unavailable"
            ) from exc
        if row is None:
            raise ValueError("application document version is unavailable")
        version = DocumentVersion.model_validate(row[0])
        if version.uploader_id != requester_id:
            raise ValueError("application requester identity changed")
        if version.cloud_knowledge is None or version.cloud_knowledge.application is None:
            return None
        if row[1] is None or row[2] is None:
            raise ValueError("application prior authority is unavailable")
        request = CloudApplicationRequest.model_validate(row[1])
        expected = version.version_id if version.active else request.expected_active_version_id
        if row[4] != expected:
            raise ValueError("application expected active generation changed")
        authority = CloudPolicyAuthority.model_validate(row[2])
        validate_application_version(authority, request, version, row[3])
        if authority.approved_by is None:
            raise ValueError("independent policy reviewer is unavailable")
        return CloudApplicationAuthorization(request=request, approved_by=authority.approved_by)
