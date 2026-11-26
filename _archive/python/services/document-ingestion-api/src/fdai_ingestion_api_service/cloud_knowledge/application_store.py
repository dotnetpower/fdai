"""API-owned human-policy setup and immutable application reservations."""

from __future__ import annotations

import psycopg
from fdai_service_contracts.cloud_knowledge_application import (
    CloudApplicationPolicy,
    CloudApplicationRequest,
    CloudPolicyAuthority,
)


class PostgresCloudApplicationStore:
    """No package, requester, or environment setting can approve a policy."""

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    async def propose(self, policy: CloudApplicationPolicy, *, actor_id: str) -> str:
        authority = CloudPolicyAuthority(policy=policy, author_id=actor_id)
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            await conn.execute(
                "INSERT INTO document_knowledge_policy (digest, policy_id, revision, payload) "
                "VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (digest) DO NOTHING",
                (policy.digest, policy.policy_id, policy.revision, authority.model_dump_json()),
            )
            row = await (
                await conn.execute(
                    "SELECT payload FROM document_knowledge_policy WHERE digest = %s",
                    (policy.digest,),
                )
            ).fetchone()
            if row is None or CloudPolicyAuthority.model_validate(row[0]).author_id != actor_id:
                raise ValueError("policy proposal belongs to another authenticated author")
            await conn.execute(
                "INSERT INTO document_knowledge_policy_audit (policy_digest, actor_id, action) "
                "VALUES (%s, %s, 'proposed')",
                (policy.digest, actor_id),
            )
        return policy.digest

    async def get(self, digest: str) -> CloudPolicyAuthority:
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            row = await (
                await conn.execute(
                    "SELECT payload FROM document_knowledge_policy WHERE digest = %s", (digest,)
                )
            ).fetchone()
        if row is None:
            raise ValueError("application policy is unavailable")
        authority = CloudPolicyAuthority.model_validate(row[0])
        if authority.policy.digest != digest:
            raise ValueError("application policy identity changed")
        return authority

    async def review(self, digest: str, *, actor_id: str, revoke: bool = False) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"cloud-policy:{digest}",),
            )
            row = await (
                await conn.execute(
                    "SELECT payload, clock_timestamp() FROM document_knowledge_policy "
                    "WHERE digest = %s FOR UPDATE",
                    (digest,),
                )
            ).fetchone()
            if row is None:
                raise ValueError("application policy is unavailable")
            authority = CloudPolicyAuthority.model_validate(row[0])
            now = row[1]
            if authority.policy.digest != digest:
                raise ValueError("application policy identity changed")
            if revoke:
                updates = {"revoked_at": now}
            else:
                authority.require_independent_reviewer(actor_id, now)
                updates = {"approved_by": actor_id, "approved_at": now}
            updated = CloudPolicyAuthority.model_validate(authority.model_dump() | updates)
            await conn.execute(
                "UPDATE document_knowledge_policy SET payload = %s::jsonb WHERE digest = %s",
                (updated.model_dump_json(), digest),
            )
            await conn.execute(
                "INSERT INTO document_knowledge_policy_audit (policy_digest, actor_id, action) "
                "VALUES (%s, %s, %s)",
                (digest, actor_id, "revoked" if revoke else "approved"),
            )

    async def reserve(self, request: CloudApplicationRequest) -> CloudApplicationRequest:
        """Pin one nonce per upload; identical retries reuse it and cannot change policy or user."""
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            await conn.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                (f"cloud-policy:{request.policy_digest}",),
            )
            policy_row = await (
                await conn.execute(
                    "SELECT payload, clock_timestamp() FROM document_knowledge_policy "
                    "WHERE digest = %s",
                    (request.policy_digest,),
                )
            ).fetchone()
            if policy_row is None:
                raise ValueError("application authority is unavailable")
            authority = CloudPolicyAuthority.model_validate(policy_row[0])
            authority.require_current(request.requester_id, policy_row[1])
            if (
                authority.policy.digest != request.policy_digest
                or not request.requested_at <= policy_row[1] < request.expires_at
            ):
                raise ValueError("application request authority changed or expired")
            await conn.execute(
                "INSERT INTO document_knowledge_application "
                "(upload_id, nonce, policy_digest, payload) VALUES (%s, %s, %s, %s::jsonb) "
                "ON CONFLICT (upload_id) DO NOTHING",
                (
                    request.upload_id,
                    request.nonce,
                    request.policy_digest,
                    request.model_dump_json(),
                ),
            )
            row = await (
                await conn.execute(
                    "SELECT payload FROM document_knowledge_application WHERE upload_id = %s",
                    (request.upload_id,),
                )
            ).fetchone()
        if row is None:
            raise ValueError("application reservation is unavailable")
        persisted = CloudApplicationRequest.model_validate(row[0])
        mutable = {"nonce", "requested_at", "expires_at"}
        if persisted.model_dump(exclude=mutable) != request.model_dump(exclude=mutable):
            raise ValueError("application retry changed its immutable binding")
        return persisted
