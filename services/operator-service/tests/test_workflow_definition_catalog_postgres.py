"""Real PostgreSQL proof of the Operator workflow definition grant and principal predicates."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from fdai_operator_service.environment import EXPECTED_DATABASE_ROLE
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
)
from fdai_operator_service.postgres_workflow_definitions import (
    PostgresWorkflowDefinitionCatalog,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration

_INSERT_DEFINITION = (
    "INSERT INTO workflow_definition (definition_id, workflow_name, workflow_version,"
    " schema_version, definition_hash, action_catalog_digest, resolved_action_versions,"
    " workflow_document, origin, visibility, lifecycle, owner_ref, created_at)"
    " VALUES (%(definition_id)s, %(name)s, '1.0.0', '1.0.0', %(hash)s, 'sha256:catalog',"
    " '{}'::jsonb, %(document)s::jsonb, %(origin)s, %(visibility)s, 'draft', %(owner)s,"
    " %(created_at)s)"
)


def _admin_dsn() -> str:
    if os.environ.get("FDAI_SERVICE_MIGRATIONS_READY") != "1":
        pytest.skip("service-owned migrations are not ready")
    value = os.environ.get("FDAI_SERVICE_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("FDAI_SERVICE_DATABASE_URL is unset")
    dsn = value.replace("postgresql+psycopg://", "postgresql://", 1)
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("workflow definition database test requires a loopback-only database")
    return dsn


def _definition(
    definition_id: str,
    origin: str,
    visibility: str,
    owner: str | None,
) -> dict[str, object]:
    name = f"wf-{definition_id}"
    return {
        "definition_id": definition_id,
        "name": name,
        "hash": f"sha256:{definition_id}",
        "document": json.dumps({"name": name, "steps": []}),
        "origin": origin,
        "visibility": visibility,
        "owner": owner,
        "created_at": datetime(2026, 9, 29, tzinfo=UTC),
    }


async def test_operator_role_reads_only_the_principal_scope_from_real_tables() -> None:
    admin = _admin_dsn()
    suffix = uuid.uuid4().hex[:12]
    principal_a = f"principal-a-{suffix}"
    principal_b = f"principal-b-{suffix}"
    definitions = {
        "upstream": _definition(f"wd-upstream-{suffix}", "upstream", "global", None),
        "tenant": _definition(f"wd-tenant-{suffix}", "tenant", "global", None),
        "a_private": _definition(f"wd-a-{suffix}", "user", "private", principal_a),
        "b_private": _definition(f"wd-b-{suffix}", "user", "private", principal_b),
        "team": _definition(f"wd-team-{suffix}", "tenant", "team", principal_a),
    }
    denied = _definition(f"wd-denied-{suffix}", "upstream", "global", None)
    definition_ids = [str(row["definition_id"]) for row in (*definitions.values(), denied)]
    binding_ids = [f"binding-a-{suffix}", f"binding-b-{suffix}"]
    async with await psycopg.AsyncConnection.connect(admin, autocommit=True) as admin_connection:
        try:
            for row in definitions.values():
                await admin_connection.execute(_INSERT_DEFINITION, row)
            for principal, binding_id in zip((principal_a, principal_b), binding_ids, strict=True):
                await admin_connection.execute(
                    "INSERT INTO workflow_binding (principal_id, binding_id, definition_id,"
                    " trigger, enabled, parameters, created_at, updated_at)"
                    " VALUES (%s, %s, %s, 'deck_open', false, '{}'::jsonb, NOW(), NOW())",
                    (principal, binding_id, definitions["upstream"]["definition_id"]),
                )
            operator_dsn = make_conninfo(admin, options=f"-c role={EXPECTED_DATABASE_ROLE}")
            store = PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=operator_dsn))

            result = await PostgresWorkflowDefinitionCatalog(store._fetch_all).read(principal_a)

            groups = result.payload["groups"]
            assert isinstance(groups, dict)
            visible = {
                str(entry["definition_id"]): group
                for group, entries in groups.items()
                if isinstance(entries, list)
                for entry in entries
                if isinstance(entry, dict) and str(entry["definition_id"]).endswith(suffix)
            }
            assert visible == {
                f"wd-upstream-{suffix}": "built_in",
                f"wd-tenant-{suffix}": "shared",
                f"wd-a-{suffix}": "mine",
            }
            bindings = result.payload["bindings"]
            assert isinstance(bindings, list)
            assert [binding["binding_id"] for binding in bindings if isinstance(binding, dict)] == [
                f"binding-a-{suffix}"
            ]
            with pytest.raises(PostgresFamilyStoreUnavailable):
                await store._fetch_all(f"{_INSERT_DEFINITION} RETURNING definition_id", denied)
            privileges = await admin_connection.execute(
                "SELECT table_name, privilege, has_table_privilege(%s, table_name, privilege)"
                " FROM unnest(ARRAY['workflow_definition', 'workflow_binding']) AS table_name,"
                " unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS privilege",
                (EXPECTED_DATABASE_ROLE,),
            )
            granted = {
                (str(table), str(privilege))
                for table, privilege, allowed in await privileges.fetchall()
                if allowed
            }
            assert granted == {("workflow_definition", "SELECT"), ("workflow_binding", "SELECT")}
        finally:
            await admin_connection.execute(
                "DELETE FROM workflow_binding WHERE binding_id = ANY(%s)", (binding_ids,)
            )
            await admin_connection.execute(
                "DELETE FROM workflow_definition WHERE definition_id = ANY(%s)", (definition_ids,)
            )
