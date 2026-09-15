"""Actual private semantic storage and accepted-source SQL across independent service roles."""

from __future__ import annotations

import hashlib
import json
import runpy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
import yaml
from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.handover_envelopes import HandoverEnvelopeReader
from fdai.delivery.identity.handover_semantic_sources import CurrentAcceptedHandoverSources
from fdai.delivery.persistence.postgres_handover_semantics import PostgresHandoverSemanticPackages
from fdai.rule_catalog.pipeline.distill.handover_retention import retention_descriptor
from fdai.rule_catalog.pipeline.distill.handover_rules import HandoverRuleCompiler
from fdai.rule_catalog.pipeline.distill.handover_semantics import (
    HandoverSemanticCompilation,
    HandoverSemanticReview,
    HandoverSemanticVerification,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.runtime.core_handover import CurrentCoreHandoverSource
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.distiller import AbstainingDistiller
from fdai_document_worker_service.artifact_manifest import attach_artifact_manifest
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentDisposition,
    DocumentEnvelope,
    DocumentIndexState,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    StructuralUnit,
)
from fdai_service_contracts.handover_knowledge import notice_for_source
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt
from psycopg.types.json import Jsonb

_support = runpy.run_path(str(Path(__file__).with_name("test_core_handover_read_postgres.py")))
database = _support["database"]
_role = _support["_role"]
_ready = _support["_ready"]
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "service-migrations/branches/core-control-plane/versions/20260914_core_handover_semantics.py"
)
pytestmark = pytest.mark.integration


def _install(database):
    statements = []
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(str(MIGRATION))["upgrade"]()
    with psycopg.connect(database) as connection:
        for statement in statements:
            connection.execute(statement)


async def _source(database, tmp_path, *, with_rule=False):
    fixture = await _ready(database)
    _install(database)
    at = fixture.clock["at"]
    version = DocumentVersion(
        document_id=fixture.document_id,
        version_id=fixture.version_id,
        upload_id=uuid4(),
        source_name="example.docx",
        source_sha256="a" * 64,
        size_bytes=100,
        media_type="application/docx",
        observed_format="docx",
        state=DocumentState.READY,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(
            reference="acl:example",
            collection_id="handover",
            reader_groups=("group:reader",),
        ),
        retention=RetentionPolicy(
            policy_version="example:1", derived_expires_at=at + timedelta(days=1)
        ),
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        uploader_id="human:subject",
        created_at=at,
        updated_at=at,
        active=True,
        available=True,
        disposition=DocumentDisposition.GOVERNED_KNOWLEDGE,
        index_state=DocumentIndexState.ACTIVE,
        retention_state=DocumentRetentionState.LIVE,
    )
    envelope = DocumentEnvelope(
        document_id=fixture.document_id,
        version_id=fixture.version_id,
        source_sha256="a" * 64,
        size_bytes=100,
        media_type="application/docx",
        observed_format="docx",
        collection_id="handover",
        purposes=version.purposes,
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="acl:example",
        units=(
            StructuralUnit(
                unit_id="unit:1",
                kind="paragraph",
                locator="docx/paragraph:1",
                text="Example service is owned by Example team.",
            ),
        ),
        extractor_name="synthetic",
        extractor_version="1",
    )
    if with_rule:
        rule = yaml.safe_load(
            (ROOT / "rule-catalog/catalog/object-storage.public-access.deny.yaml").read_text()
        )
        rule.pop("source")
        rule.pop("provenance")
        envelope = envelope.model_copy(
            update={
                "units": (
                    *envelope.units,
                    StructuralUnit(
                        unit_id="unit:2",
                        kind="paragraph",
                        locator="docx/paragraph:2",
                        text=json.dumps({"kind": "fdai.rule.candidate.v1", "rule": rule}),
                    ),
                )
            }
        )
    envelope = attach_artifact_manifest(envelope=envelope, version=version, observed_at=at)
    path = (
        tmp_path
        / "derived/documents"
        / fixture.document_id.hex
        / "versions"
        / fixture.version_id.hex
        / "envelope.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(envelope.model_dump_json())
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE document_version SET payload=%s", (Jsonb(version.model_dump(mode="json")),)
        )
    for principal, backup in (
        (Principal("human:backup", frozenset({Role.READER})), fixture.backup.case_id),
        (Principal("human:owner", frozenset({Role.OWNER})), None),
    ):
        fixture.goal = await fixture.core.goals.accept(
            goal_id=fixture.goal.goal_id,
            expected_revision=fixture.goal.revision,
            principal=principal,
            backup_case_id=backup,
            now=at,
        )
    notice = notice_for_source(fixture.goal.to_dict(), source="core", at=at)
    source = CurrentAcceptedHandoverSources(
        HandoverKnowledgeSourceCheck(
            CurrentCoreHandoverSource(fixture.core.source, fixture.core), lambda: at
        ),
        fixture.core.admission,
        HandoverEnvelopeReader(local_root=tmp_path),
        lambda: at,
    )
    return fixture, source, notice, envelope, path


async def test_real_accepted_source_reads_original_complete_normalized_envelope(database, tmp_path):
    fixture, source, notice, envelope, _ = await _source(database, tmp_path)
    assert await source.read(notice) == (envelope,)
    assert await source.read(notice) == (envelope,)
    assert fixture.goal.state.value == "accepted"


@pytest.mark.parametrize(
    "change", ["purpose", "acl", "protection", "bytes", "reviewer", "withdrawal"]
)
async def test_current_source_constraints_prevent_semantic_content_reuse(
    database, tmp_path, change
):
    fixture, source, notice, envelope, path = await _source(database, tmp_path)
    if change in {"purpose", "acl", "protection"}:
        field, value = {
            "purpose": ("purposes", ["knowledge"]),
            "acl": (
                "access",
                {
                    "reference": "acl:other",
                    "collection_id": "handover",
                    "reader_groups": [],
                },
            ),
            "protection": ("protection_state", "unknown"),
        }[change]
        with psycopg.connect(database) as connection:
            connection.execute(
                "UPDATE document_version SET payload=payload || %s", (Jsonb({field: value}),)
            )
    elif change == "bytes":
        raw = envelope.model_dump(mode="json")
        raw["units"][0]["text"] = "Changed assertion."
        path.write_text(json.dumps(raw))
    elif change == "reviewer":
        fixture.identities.pop("human:owner")
    else:
        with psycopg.connect(database) as connection:
            connection.execute("UPDATE document_version SET active=false")
    with pytest.raises((ValueError, PermissionError)):
        await source.read(notice)


async def test_real_private_package_claims_are_immutable_audited_and_hidden_from_operator(
    database,
    tmp_path,
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    assert not await packages.claim(key, identity)
    assert (await packages.read(key))["package"] is None
    await packages.complete(key, identity, package)
    await packages.complete(key, identity, package)
    assert (await packages.read(key))["package"] == package
    with pytest.raises(ValueError, match="conflicts"):
        await packages.complete(key, identity, {**package, "private_rule": "Different body"})
    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute("SELECT * FROM handover_semantic_package")
    with psycopg.connect(database) as admin:
        entries = admin.execute(
            "SELECT entry FROM audit_log WHERE action_kind LIKE 'handover.semantic.%'"
        ).fetchall()
        assert len(entries) == 2
        assert "Synthetic source-restricted" not in json.dumps(entries)
        with pytest.raises(psycopg.errors.RaiseException):
            admin.execute("UPDATE handover_semantic_package SET package='{}' WHERE key=%s", (key,))


def _private_package(notice, envelope, *, compiler_digest="c" * 64):
    identity = {
        "source_id": notice.source_id,
        "source_revision": notice.goal_revision,
        "source_digest": notice.source_digest,
        "compiler_digest": compiler_digest,
    }
    key = (
        "human_assignment:semantic-package:"
        + hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    package = {
        "identity": identity,
        "retention": retention_descriptor(notice, (envelope,)),
        "private_rule": "Synthetic source-restricted Rule body.",
    }
    receipt = HandoverSemanticReceipt(
        **identity,
        package_ref=key,
        package_digest="d" * 64,
        disposition="held",
        reason="no_supported_candidates",
    )
    return key, identity, {**package, "receipt": receipt.model_dump(mode="json")}


async def test_real_sql_source_compiler_and_independent_package_review(database, tmp_path):
    fixture, source, notice, envelope, _ = await _source(database, tmp_path, with_rule=True)
    rule = json.loads(envelope.units[1].text)["rule"]
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    verifier = HandoverSemanticVerification(
        HandoverRuleCompiler(
            PackageResourceSchemaRegistry(),
            frozenset({rule["remediates"]}),
            frozenset({"object-storage"}),
            ROOT / "policies",
            ROOT / "rule-catalog/remediation",
        ),
        lambda envelope: VerificationContext(
            ontology_release="b" * 64,
            current_graph_revision="unobserved:review-only",
            object_types=frozenset(),
            links=(),
            entities=(),
            source_policies=(),
            claim_text=(),
        ),
        "c" * 64,
    )
    compiler = HandoverSemanticCompilation(
        source,
        packages,
        AbstainingDistiller(),
        verifier,
        lambda: fixture.clock["at"],
    )
    reviewer = HandoverSemanticReview(
        replace(source),
        packages,
        verifier,
        lambda: fixture.clock["at"],
    )
    receipt = await compiler.compile(notice)
    assert receipt.rule_count == 1 and receipt.ontology_count == 0
    assert await reviewer.review(notice, receipt) == receipt
    assert await compiler.compile(notice) == receipt
    retained = await packages.read(receipt.package_ref)
    assert retained["package"]["documents"][0]["rules"][0]["source_units"][0]["locator"] == (
        "docx/paragraph:2"
    )
    with psycopg.connect(database) as connection:
        rows = connection.execute(
            "SELECT entry FROM audit_log WHERE action_kind LIKE 'handover.semantic.%'"
        ).fetchall()
        assert len(rows) == 2
        assert "object-storage.public-access.deny" not in json.dumps(rows)
    fixture.identities.pop("human:owner")
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)


@pytest.mark.parametrize("stage", ["claim", "complete"])
async def test_real_package_audit_failure_rolls_back_its_transition(
    database,
    tmp_path,
    monkeypatch,
    stage,
):
    from fdai.delivery.persistence.postgres import PostgresStateStore

    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    if stage == "complete":
        assert await packages.claim(key, identity)

    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(PostgresStateStore, "_append_audit_in_transaction", fail)
    with pytest.raises(RuntimeError, match="Synthetic audit"):
        if stage == "claim":
            await packages.claim(key, identity)
        else:
            await packages.complete(key, identity, package)
    retained = await packages.read(key)
    if stage == "claim":
        assert retained is None
    else:
        assert retained["package"] is None


async def test_private_package_adapter_refuses_administrator_role(database):
    from fdai.delivery.persistence.postgres import PostgresStateStoreConfig

    with pytest.raises(PermissionError):
        await PostgresHandoverSemanticPackages(PostgresStateStoreConfig(dsn=database)).read(
            "human_assignment:semantic-package:" + "a" * 64
        )


@pytest.mark.parametrize("legal_hold", [True, False, None])
async def test_real_retirement_keeps_claim_and_honors_current_legal_hold(
    database,
    tmp_path,
    legal_hold,
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE document_version SET payload=jsonb_set(payload,'{retention,legal_hold}',%s)",
            (Jsonb(legal_hold),),
        )
    assert await packages.reconcile(notice, withdrawn=True) == 1
    assert (await packages.read(key))["retired"] is True
    assert not await packages.claim(key, identity)
    with psycopg.connect(database) as admin:
        row = admin.execute(
            "SELECT package,receipt,identity,retired_at "
            "FROM handover_semantic_package WHERE key=%s",
            (key,),
        ).fetchone()
        assert (row[0] is None) is (legal_hold is False)
        assert row[1] == package["receipt"] and row[2] == identity and row[3] is not None
    await packages.reconcile(notice, withdrawn=False)
    with psycopg.connect(database) as admin:
        count = admin.execute(
            "SELECT count(*) FROM audit_log WHERE action_kind='handover.semantic.retired'"
        ).fetchone()[0]
        assert count == 1
        if legal_hold is not False:
            with pytest.raises(psycopg.errors.RaiseException):
                admin.execute(
                    "UPDATE handover_semantic_package SET package=NULL WHERE key=%s", (key,)
                )


async def test_real_legal_hold_release_scrubs_without_reopening_the_original_attempt(
    database, tmp_path
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE document_version SET payload=jsonb_set(payload,'{retention,legal_hold}','true')"
        )
    await packages.reconcile(notice, withdrawn=True)
    with psycopg.connect(database) as admin:
        assert admin.execute(
            "SELECT package IS NOT NULL FROM handover_semantic_package"
        ).fetchone()[0]
        admin.execute(
            "UPDATE document_version SET payload="
            "jsonb_set(payload,'{retention,legal_hold}','false')"
        )
    await packages.reconcile(notice, withdrawn=False)
    with psycopg.connect(database) as admin:
        assert admin.execute("SELECT package IS NULL FROM handover_semantic_package").fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            admin.execute(
                "UPDATE handover_semantic_package SET retired_at=NULL,package=%s",
                (Jsonb(package),),
            )


async def test_real_retirement_audit_failure_preserves_package(database, tmp_path, monkeypatch):
    from fdai.delivery.persistence.postgres import PostgresStateStore

    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)

    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic retirement audit failure")

    monkeypatch.setattr(PostgresStateStore, "_append_audit_in_transaction", fail)
    with pytest.raises(RuntimeError):
        await packages.reconcile(notice, withdrawn=True)
    with psycopg.connect(database) as admin:
        row = admin.execute("SELECT package,retired_at FROM handover_semantic_package").fetchone()
        assert row[0] == package and row[1] is None


async def test_real_source_expiry_blocks_read_before_retirement_consumer_runs(database, tmp_path):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE document_version SET payload="
            "jsonb_set(payload,'{retention,derived_expires_at}',%s)",
            (Jsonb((fixture.clock["at"] - timedelta(seconds=1)).isoformat()),),
        )
    assert (await packages.read(key))["package"] is None
    with psycopg.connect(database) as admin:
        assert admin.execute("SELECT retired_at IS NULL FROM handover_semantic_package").fetchone()[
            0
        ]
    await packages.reconcile(notice, withdrawn=False)
    with psycopg.connect(database) as admin:
        assert admin.execute("SELECT package IS NULL FROM handover_semantic_package").fetchone()[0]


async def test_real_retention_scan_rotates_past_legal_hold_without_unbounded_work(
    database, tmp_path
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE document_version SET payload=jsonb_set(payload,'{retention,legal_hold}','true')"
        )
    for index in range(27):
        key, identity, package = _private_package(notice, envelope, compiler_digest=f"{index:064x}")
        assert await packages.claim(key, identity)
        await packages.complete(key, identity, package)
    assert await packages.reconcile(notice, withdrawn=True) == 25
    with psycopg.connect(database) as admin:
        assert (
            admin.execute(
                "SELECT count(*) FROM handover_semantic_package WHERE retired_at IS NOT NULL"
            ).fetchone()[0]
            == 25
        )
    assert await packages.reconcile(notice, withdrawn=True) == 25
    with psycopg.connect(database) as admin:
        assert (
            admin.execute(
                "SELECT count(*) FROM handover_semantic_package WHERE retired_at IS NOT NULL"
            ).fetchone()[0]
            == 27
        )
        assert (
            admin.execute(
                "SELECT count(*) FROM handover_semantic_package WHERE package IS NOT NULL"
            ).fetchone()[0]
            == 27
        )


async def test_real_missing_source_policy_holds_bytes_instead_of_assuming_no_legal_hold(
    database, tmp_path
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)
    with psycopg.connect(database) as admin:
        admin.execute("DELETE FROM document_version")
    await packages.reconcile(notice, withdrawn=True)
    assert (await packages.read(key))["retired"] is True
    with psycopg.connect(database) as admin:
        assert admin.execute(
            "SELECT package IS NOT NULL FROM handover_semantic_package"
        ).fetchone()[0]


async def test_real_policy_read_failure_does_not_erase_or_falsely_retire_content(
    database, tmp_path
):
    fixture, _, notice, envelope, _ = await _source(database, tmp_path)
    packages = PostgresHandoverSemanticPackages(fixture.core.source.config)
    key, identity, package = _private_package(notice, envelope)
    assert await packages.claim(key, identity)
    await packages.complete(key, identity, package)
    with psycopg.connect(database) as admin:
        admin.execute(
            "REVOKE EXECUTE ON FUNCTION fdai_core_handover_package_policy(TEXT) FROM fdai_core"
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await packages.reconcile(notice, withdrawn=True)
    with psycopg.connect(database) as admin:
        row = admin.execute("SELECT package,retired_at FROM handover_semantic_package").fetchone()
        assert row[0] == package and row[1] is None
