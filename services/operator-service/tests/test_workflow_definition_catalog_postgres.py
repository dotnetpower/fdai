"""Real PostgreSQL proof of the Operator workflow definition grant and principal predicates."""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from fdai_operator_service.environment import EXPECTED_DATABASE_ROLE
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
)
from fdai_operator_service.postgres_workflow_authoring import PostgresWorkflowAuthoringStore
from fdai_operator_service.postgres_workflow_definitions import (
    PostgresWorkflowDefinitionCatalog,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MATERIALIZE_SCRIPT = _REPO_ROOT / "scripts/deployment/local/materialize-authoritative-catalogs.py"

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
            writer = PostgresWorkflowAuthoringStore(store)
            draft = await writer.create_definition(
                principal_id=principal_a,
                idempotency_key=f"draft-{suffix}",
                expected_revision="new",
                payload={
                    "confirmed": True,
                    "workflow": {
                        "schema_version": "1.0.0",
                        "name": f"wf-draft-{suffix}",
                        "version": "1.0.0",
                        "default_mode": "shadow",
                        "trigger": {"kind": "signal", "signal_type": "object.event"},
                        "promotion_gate": {
                            "min_shadow_days": 1,
                            "min_samples": 1,
                            "min_accuracy": 1,
                            "max_policy_escapes": 0,
                        },
                        "steps": [{"id": "notify", "action_type_ref": "tool.notify"}],
                    },
                },
            )
            assert draft.status_code == 201
            created_id = str(draft.payload["definition"]["definition_id"])
            definition_ids.append(created_id)
            binding = await writer.create_binding(
                principal_id=principal_a,
                idempotency_key=f"binding-{suffix}",
                expected_revision="new",
                payload={
                    "confirmed": True,
                    "definition_id": created_id,
                    "trigger": "deck_open",
                },
            )
            assert binding.payload["revision"] == 1
            replay = await writer.create_binding(
                principal_id=principal_a,
                idempotency_key=f"binding-{suffix}",
                expected_revision="new",
                payload={
                    "confirmed": True,
                    "definition_id": created_id,
                    "trigger": "deck_open",
                },
            )
            assert replay.payload["duplicate"] is True
            with pytest.raises(PostgresFamilyStoreUnavailable):
                await store._fetch_all(f"{_INSERT_DEFINITION} RETURNING definition_id", denied)
            spoofed_owner = _definition(f"wd-spoof-{suffix}", "user", "global", principal_a)
            definition_ids.append(str(spoofed_owner["definition_id"]))
            with pytest.raises(PostgresFamilyStoreUnavailable):
                await store._fetch_all(
                    f"{_INSERT_DEFINITION} RETURNING definition_id", spoofed_owner
                )
            with pytest.raises(PostgresFamilyStoreUnavailable):
                await store._fetch_all(
                    "INSERT INTO workflow_binding (principal_id, binding_id, definition_id,"
                    " trigger, enabled, parameters, created_at, updated_at)"
                    " VALUES (%(principal)s, %(binding)s, %(definition)s, 'deck_open', false,"
                    " '{}'::jsonb, NOW(), NOW()) RETURNING binding_id",
                    {
                        "principal": principal_a,
                        "binding": f"binding-cross-{suffix}",
                        "definition": definitions["b_private"]["definition_id"],
                    },
                )
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
            assert granted == {
                ("workflow_definition", "SELECT"),
                ("workflow_definition", "INSERT"),
                ("workflow_binding", "SELECT"),
                ("workflow_binding", "INSERT"),
                ("workflow_binding", "UPDATE"),
                ("workflow_binding", "DELETE"),
            }
        finally:
            await admin_connection.execute(
                "DELETE FROM operator_workflow_authoring_audit WHERE principal_id = %s",
                (principal_a,),
            )
            await admin_connection.execute(
                "DELETE FROM workflow_binding WHERE binding_id = ANY(%s) OR principal_id = %s",
                (binding_ids, principal_a),
            )
            await admin_connection.execute(
                "DELETE FROM workflow_definition WHERE definition_id = ANY(%s)", (definition_ids,)
            )


def _materialize_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "materialize_authoritative_catalogs", _MATERIALIZE_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_catalog_seed_materializes_reviewed_builtins_for_operator_reads() -> None:
    admin = _admin_dsn()
    module = _materialize_module()
    snapshots = module.catalog_snapshots(_REPO_ROOT)
    workflows = snapshots[module.WORKFLOW_CATALOG_KEY]["workflows"]
    expected = {
        f"workflow-definition:upstream:{workflow['name']}:{workflow['version']}"
        for workflow in workflows
    }
    assert expected
    async with await psycopg.AsyncConnection.connect(admin, autocommit=True) as admin_connection:
        try:
            await module._seed_builtin_workflow_definitions(admin, snapshots=snapshots)
            await module._seed_builtin_workflow_definitions(admin, snapshots=snapshots)
            cursor = await admin_connection.execute(
                "SELECT definition_id, origin, visibility, lifecycle, owner_ref, source_ref"
                " FROM workflow_definition WHERE definition_id = ANY(%s)",
                (sorted(expected),),
            )
            rows = await cursor.fetchall()
            assert {str(row[0]) for row in rows} == expected
            assert {(row[1], row[2], row[3], row[4]) for row in rows} == {
                ("upstream", "global", "shadow", None)
            }
            assert all(str(row[5]).startswith("rule-catalog/workflows/") for row in rows)

            operator_dsn = make_conninfo(admin, options=f"-c role={EXPECTED_DATABASE_ROLE}")
            store = PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=operator_dsn))
            result = await PostgresWorkflowDefinitionCatalog(store._fetch_all).read(
                f"principal-seed-{uuid.uuid4().hex[:12]}"
            )
            groups = result.payload["groups"]
            assert isinstance(groups, dict)
            built_in = {
                str(entry["definition_id"])
                for entry in groups.get("built_in", [])
                if isinstance(entry, dict)
            }
            assert expected <= built_in
        finally:
            await admin_connection.execute(
                "DELETE FROM workflow_definition WHERE definition_id = ANY(%s)"
                " AND origin = 'upstream'",
                (sorted(expected),),
            )
