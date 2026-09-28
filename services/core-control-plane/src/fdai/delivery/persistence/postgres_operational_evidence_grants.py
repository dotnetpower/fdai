"""Catalog readback that decides whether the proof store is writer-exclusive."""

from __future__ import annotations

from fdai.core.operational_evidence.separation import ProofStoreGrantReadback
from fdai.delivery.persistence.postgres_operational_evidence import (
    EXPECTED_GUARDS,
    PROOF_TABLES,
    READER_ROLE,
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    role_bound_connection,
)


async def read_proof_store_grants(
    config: PostgresOperationalEvidenceConfig,
    *,
    reader_roles: tuple[str, ...] = (READER_ROLE, "fdai_core"),
    allowed_writer_members: tuple[str, ...] = (),
) -> ProofStoreGrantReadback:
    """Read table grants, writer-role memberships, and guards from the catalog.

    The table owner is excluded from grant holders: its implicit privileges are neutralized by
    the writer and immutability triggers, and administrative ownership stays a trusted root.
    """

    async with role_bound_connection(config) as connection:
        grants = await (
            await connection.execute(
                "SELECT c.relname, a.privilege_type, "
                "CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END "
                "AS grantee FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a "
                "WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(%s) "
                "AND a.grantee <> c.relowner",
                (list(PROOF_TABLES),),
            )
        ).fetchall()
        members = await (
            await connection.execute(
                "SELECT pg_get_userbyid(m.member) AS member FROM pg_auth_members m "
                "WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = %s)",
                (VERIFIER_ROLE,),
            )
        ).fetchall()
        guards = await (
            await connection.execute(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(%s) "
                "AND NOT t.tgisinternal AND t.tgenabled <> 'D'",
                (list(PROOF_TABLES),),
            )
        ).fetchall()
    return ProofStoreGrantReadback(
        writer_role=VERIFIER_ROLE,
        reader_roles=reader_roles,
        insert_holders=tuple(
            sorted({row["grantee"] for row in grants if row["privilege_type"] == "INSERT"})
        ),
        mutation_holders=tuple(
            sorted(
                {
                    row["grantee"]
                    for row in grants
                    if row["privilege_type"] in {"UPDATE", "DELETE", "TRUNCATE"}
                }
            )
        ),
        writer_role_members=tuple(sorted({row["member"] for row in members})),
        immutability_guards=tuple(
            sorted(
                {
                    str(row["tgname"]).removeprefix("operational_")
                    for row in guards
                    if str(row["tgname"]).startswith("operational_evidence_")
                }
            )
        ),
        expected_guards=EXPECTED_GUARDS,
        allowed_writer_members=allowed_writer_members,
    )


__all__ = ["read_proof_store_grants"]
