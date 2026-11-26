"""Real SQL admission and reviewer ACL checks without raw document-table grants."""

from __future__ import annotations

import runpy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.iam.errors import IamUnavailableError
from fdai_operator_service.families.iam.handover_postgres import PostgresHandoverEvidenceVerifier
from psycopg.types.json import Jsonb

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
pytestmark = pytest.mark.integration


def _document(database, **changes):
    document_id, version_id = uuid4(), uuid4()
    payload = {
        "uploader_id": "human:subject",
        "source_sha256": "a" * 64,
        "available": True,
        "disposition": "governed_knowledge",
        "index_state": "active",
        "retention_state": "live",
        "access": {"reader_groups": ["group:readers"]},
        **changes,
    }
    with psycopg.connect(database) as admin:
        admin.execute(
            "INSERT INTO document_version VALUES (%s,%s,'ready',true,%s)",
            (document_id, version_id, Jsonb(payload)),
        )
    return {
        "principal_id": "human:subject",
        "document_id": document_id,
        "version_id": version_id,
        "source_sha256": "a" * 64,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"disposition": "workspace_draft"},
        {"retention_state": "purged"},
        {"index_state": "tombstoned"},
        {"available": "true"},
    ],
)
async def test_operator_never_admits_ungoverned_or_withdrawn_evidence(database, changes):
    receipt = _document(database, **changes)
    verifier = PostgresHandoverEvidenceVerifier(_role(database, "fdai_operator"))
    assert not await verifier.verify(**receipt)


@pytest.mark.parametrize(
    "roles,groups,expected",
    [
        (("Reader",), ("group:readers",), True),
        (("Reader",), ("group:other",), False),
        (("Reader",), (), False),
        ((), ("group:readers",), False),
        (("BreakGlass",), ("group:readers",), False),
        (("Contributor",), (), True),
        (("Approver",), (), True),
        (("Owner",), (), True),
        (("Reader",), tuple("group:readers" for _ in range(501)), False),
    ],
)
async def test_reviewer_requires_current_ordinary_role_and_exact_document_acl(
    database, roles, groups, expected
):
    receipt = _document(database)
    verifier = PostgresHandoverEvidenceVerifier(_role(database, "fdai_operator"))
    assert await verifier.verify(**receipt)
    assert (
        await verifier.verify_review(
            **receipt,
            reviewer_id="human:backup",
            reviewer_roles=roles,
            reviewer_group_ids=groups,
        )
        is expected
    )


@pytest.mark.parametrize("change", ["self", "digest", "subject", "version"])
async def test_reviewer_boolean_never_overrides_exact_source_or_independence(database, change):
    receipt = _document(database)
    reviewer_id = "human:backup"
    if change == "self":
        reviewer_id = "HUMAN:SUBJECT"
    elif change == "digest":
        receipt["source_sha256"] = "b" * 64
    elif change == "subject":
        receipt["principal_id"] = "human:other"
    else:
        receipt["version_id"] = uuid4()
    verifier = PostgresHandoverEvidenceVerifier(_role(database, "fdai_operator"))
    assert not await verifier.verify_review(
        **receipt,
        reviewer_id=reviewer_id,
        reviewer_roles=("Owner",),
        reviewer_group_ids=(),
    )


async def test_malformed_acl_does_not_become_a_group_membership_match(database):
    receipt = _document(database, access={"reader_groups": {"group:readers": True}})
    verifier = PostgresHandoverEvidenceVerifier(_role(database, "fdai_operator"))
    assert not await verifier.verify_review(
        **receipt,
        reviewer_id="human:backup",
        reviewer_roles=("Reader",),
        reviewer_group_ids=("group:readers",),
    )


async def test_new_booleans_preserve_sql_roles_and_hold_after_rollback(database):
    receipt = _document(database)
    for role in ("fdai_core", "fdai_operator"):
        with psycopg.connect(_role(database, role)) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT payload FROM document_version")
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT fdai_verify_handover_document_admission(%s,%s,%s,%s)",
                tuple(receipt.values()),
            )
    with psycopg.connect(database) as connection:
        _support["_run_migration"](connection, _support["REVIEWER_MIGRATION"], "downgrade")
    verifier = PostgresHandoverEvidenceVerifier(_role(database, "fdai_operator"))
    with pytest.raises(IamUnavailableError):
        await verifier.verify(**receipt)


async def test_reader_refuses_an_accidentally_privileged_connection(database):
    receipt = _document(database)
    with pytest.raises(IamUnavailableError, match="Operator SQL role"):
        await PostgresHandoverEvidenceVerifier(database).verify(**receipt)
