from __future__ import annotations

import json
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres_cost_governance_validation import (
    PostgresCostGovernanceValidationStore,
)
from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
)
from fdai.shared.providers.cost_governance_lifecycle import CostEvidenceKind
from psycopg import sql
from psycopg.types.json import Jsonb

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260829_core_cost_governance_validation.py"
)
_RUNTIME_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260828_core_cost_governance_runtime.py"
)
_SETTINGS_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260831_core_cost_governance_settings.py"
)
_LIFECYCLE_REPAIR_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_cost_governance_w7_lifecycle.py"
)
_LIFECYCLE_OPERATOR_REPAIR_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_cost_governance_release_guard.py"
)
_STORE = (
    _ROOT
    / "services/core-control-plane/src/fdai/delivery/persistence"
    / "postgres_cost_governance_validation.py"
)


def _migration_sql(path: Path, name: str) -> tuple[dict[str, object], str]:
    module = runpy.run_path(str(path))
    statements: list[str] = []
    module[name].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module[name]()
    return module, "\n".join(statements)


def _sql(name: str) -> tuple[dict[str, object], str]:
    return _migration_sql(_MIGRATION, name)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_cost_validation_" + uuid4().hex[:12]
    admin = psycopg.connect(source, dbname="postgres", autocommit=True)
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except psycopg.errors.InsufficientPrivilege:
        admin.close()
        pytest.skip("validation database principal cannot create a disposable database")
    try:
        yield urlunsplit(parts._replace(path=f"/{database}"))
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
        )
        admin.close()


def test_w7_validation_tables_are_core_owned_and_evidence_is_append_only() -> None:
    module, sql = _sql("upgrade")
    expected = {
        "cost_governance_lifecycle_receipt",
        "cost_governance_campaign_episode",
        "cost_governance_validation_retention",
        "cost_governance_validation_retention_event",
    }
    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )

    assert module["migration_owner"] == "core-control-plane"
    assert set(module["owned_tables"]) == expected
    assert expected <= set(ownership["table_migrations"]["core-control-plane"])
    assert expected <= set(ownership["whole_table_writers"]["core-control-plane"])
    normalized = " ".join(sql.split())
    assert "GRANT SELECT, INSERT ON TABLE" in normalized
    assert (
        "GRANT SELECT, INSERT, UPDATE ON TABLE cost_governance_validation_retention TO fdai_core"
    ) in normalized
    assert "GRANT DELETE" not in sql
    assert "ON DELETE CASCADE" not in sql


def test_receipts_and_campaigns_pin_revision_provenance_and_idempotency() -> None:
    _, sql = _sql("upgrade")

    assert "activation_revision BIGINT NOT NULL" in sql
    assert "revision_pin_digest TEXT NOT NULL" in sql
    assert "receipt_digest TEXT NOT NULL UNIQUE" in sql
    assert "idempotency_key TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE (episode_id, idempotency_key)" in sql
    assert "UNIQUE (campaign_id, idempotency_key)" in sql
    assert "'install', 'enable', 'disable', 'upgrade', 'rollback'" in sql
    assert "'live-authoritative', 'synthetic', 'fixture', 'unit'" in sql
    assert "'beneficial-action', 'no-op', 'deny', 'hold-unresolved'" in sql
    assert "jsonb_array_length(evidence_refs) BETWEEN 1 AND 64" in sql


def test_validation_retention_is_revisioned_held_and_bounded() -> None:
    _, sql = _sql("upgrade")
    source = _STORE.read_text(encoding="utf-8")

    assert "legal_hold BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "legal_hold = (legal_hold_ref IS NOT NULL)" in sql
    assert "purged_at IS NULL OR (NOT legal_hold AND purged_at >= purge_after)" in sql
    assert "WHERE purge_after <= %s" in source
    assert "AND NOT legal_hold" in source
    assert "LIMIT %s" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "revision = revision + 1" in source
    assert "expected_revision" in source


def test_store_verifies_receipt_digest_and_campaign_cas() -> None:
    source = _STORE.read_text(encoding="utf-8")

    assert "receipt.verify_digest(expected_receipt_digest)" in source
    assert "persisted lifecycle receipt failed digest verification" in source
    assert "episode.revision != expected_revision + 1" in source
    assert "actual != expected_revision" in source
    assert source.count("ON CONFLICT DO NOTHING") >= 2
    assert "revision_pin_digest = %s" in source


def test_operator_activation_writes_canonical_w7_lifecycle_payload() -> None:
    source = _LIFECYCLE_REPAIR_MIGRATION.read_text(encoding="utf-8")
    pin = source.split("pin := jsonb_build_object(", 1)[1].split(");", 1)[0]
    payload = source.split("NEW.payload := jsonb_build_object(", 1)[1].split(");", 1)[0]

    for field in (
        "schema_version",
        "receipt_id",
        "idempotency_key",
        "operation",
        "outcome",
        "revision_pin",
        "available",
        "enabled",
        "occurred_at",
        "evidence_kind",
        "evidence_refs",
        "retention_until",
        "legal_hold",
        "legal_hold_ref",
    ):
        assert f"'{field}'" in payload
    for field in (
        "package_id",
        "package_version",
        "source_revision",
        "wheel_digest",
        "image_digest",
        "asset_manifest_digest",
        "semantic_profile_digest",
        "ontology_release_digest",
        "runtime_config_digest",
        "activation_revision",
    ):
        assert f"'{field}'" in pin


def test_release_guard_repair_disambiguates_jsonb_subtraction() -> None:
    _, upgrade = _migration_sql(_LIFECYCLE_OPERATOR_REPAIR_MIGRATION, "upgrade")
    _, downgrade = _migration_sql(_LIFECYCLE_OPERATOR_REPAIR_MIGRATION, "downgrade")

    assert "'(receipt.payload -> ''revision_pin'') - ''activation_revision'''" in upgrade
    assert "'receipt.payload -> ''revision_pin'' - ''activation_revision'''" in downgrade
    assert "EXECUTE replace(function_definition, broken_expression, fixed_expression)" in upgrade
    assert "EXECUTE replace(function_definition, fixed_expression, broken_expression)" in downgrade


async def test_live_lifecycle_receipts_round_trip_through_canonical_reader(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        for path in (
            _RUNTIME_MIGRATION,
            _MIGRATION,
            _SETTINGS_MIGRATION,
            _LIFECYCLE_REPAIR_MIGRATION,
            _LIFECYCLE_OPERATOR_REPAIR_MIGRATION,
        ):
            connection.execute(_migration_sql(path, "upgrade")[1])
        connection.execute(
            """
            SELECT * FROM fdai_register_cost_governance_release(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                "install",
                "cost-governance",
                "cost-governance",
                "0.1.3",
                _digest("a"),
                _digest("b"),
                _digest("c"),
                _digest("d"),
                "ontology-release:2026-09",
                _digest("e"),
                "f" * 40,
                _digest("0"),
                0,
                "install-request-0001",
                Jsonb(["workflow:install:1"]),
            ),
        ).fetchone()
        connection.execute(
            "SELECT * FROM fdai_set_cost_governance_enabled(%s, %s, %s, %s, %s)",
            (
                "cost-governance",
                "operator-owner",
                True,
                1,
                "enable-request-0001",
            ),
        ).fetchone()
        connection.execute(
            "SELECT * FROM fdai_set_cost_governance_enabled(%s, %s, %s, %s, %s)",
            (
                "cost-governance",
                "operator-owner",
                False,
                2,
                "disable-request-0001",
            ),
        ).fetchone()
        release_statement = """
            SELECT * FROM fdai_register_cost_governance_release(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
        """
        connection.execute(
            release_statement,
            (
                "upgrade",
                "cost-governance",
                "cost-governance",
                "0.1.3",
                _digest("1"),
                _digest("2"),
                _digest("3"),
                _digest("4"),
                "ontology-release:2026-09",
                _digest("5"),
                "1" * 40,
                _digest("6"),
                3,
                "upgrade-request-0001",
                Jsonb(["workflow:upgrade:1"]),
            ),
        ).fetchone()
        connection.execute(
            release_statement,
            (
                "rollback",
                "cost-governance",
                "cost-governance",
                "0.1.3",
                _digest("a"),
                _digest("b"),
                _digest("c"),
                _digest("d"),
                "ontology-release:2026-09",
                _digest("e"),
                "f" * 40,
                _digest("0"),
                4,
                "rollback-request-0001",
                Jsonb(["workflow:rollback:1"]),
            ),
        ).fetchone()

    receipts = await PostgresCostGovernanceValidationStore(
        dsn=disposable_database_url
    ).read_cost_lifecycle_receipts("cost-governance", limit=10)

    assert tuple(receipt.operation.value for receipt in reversed(receipts)) == (
        "install",
        "enable",
        "disable",
        "upgrade",
        "rollback",
    )
    assert all(receipt.evidence_kind.value == "live-authoritative" for receipt in receipts)
    assert tuple(receipt.revision_pin.activation_revision for receipt in receipts) == (
        5,
        4,
        3,
        2,
        1,
    )


def test_lifecycle_request_ids_bind_every_release_and_settings_input(
    disposable_database_url: str,
) -> None:
    for path in (
        _RUNTIME_MIGRATION,
        _MIGRATION,
        _SETTINGS_MIGRATION,
        _LIFECYCLE_REPAIR_MIGRATION,
    ):
        with psycopg.connect(disposable_database_url) as connection:
            connection.execute(_migration_sql(path, "upgrade")[1])

    release = (
        "install",
        "cost-governance",
        "cost-governance",
        "0.1.3",
        _digest("a"),
        _digest("b"),
        _digest("c"),
        _digest("d"),
        "ontology-release:2026-09",
        _digest("e"),
        "f" * 40,
        _digest("0"),
        0,
        "install-request-identity",
        Jsonb(["workflow:install:1"]),
    )
    statement = """
        SELECT * FROM fdai_register_cost_governance_release(
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
    """
    for values in (release, release):
        with psycopg.connect(disposable_database_url) as connection:
            assert connection.execute(statement, values).fetchone() is not None

    changed_image = (*release[:4], _digest("9"), *release[5:])
    with (
        psycopg.connect(disposable_database_url) as connection,
        pytest.raises(psycopg.DatabaseError) as release_conflict,
    ):
        connection.execute(statement, changed_image).fetchone()
    assert release_conflict.value.sqlstate == "CG004"

    settings = (
        "cost-governance",
        "operator-owner",
        True,
        1,
        "enable-request-identity",
    )
    settings_statement = "SELECT * FROM fdai_set_cost_governance_enabled(%s, %s, %s, %s, %s)"
    for values in (settings, settings):
        with psycopg.connect(disposable_database_url) as connection:
            assert connection.execute(settings_statement, values).fetchone() is not None

    changed_actor = (settings[0], "another-owner", *settings[2:])
    with (
        psycopg.connect(disposable_database_url) as connection,
        pytest.raises(psycopg.DatabaseError) as settings_conflict,
    ):
        connection.execute(settings_statement, changed_actor).fetchone()
    assert settings_conflict.value.sqlstate == "CG004"

    with psycopg.connect(disposable_database_url) as connection:
        refs = connection.execute(
            """
            SELECT evidence_refs
              FROM cost_governance_lifecycle_receipt
             ORDER BY activation_revision
            """
        ).fetchall()
    assert all(
        sum(isinstance(item, str) and item.startswith("request:sha256:") for item in row[0]) == 1
        for row in refs
    )


async def test_legacy_noncanonical_settings_receipt_is_retained_but_not_admitted(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        for path in (_RUNTIME_MIGRATION, _MIGRATION, _SETTINGS_MIGRATION):
            connection.execute(_migration_sql(path, "upgrade")[1])
        connection.execute(
            """
            INSERT INTO vertical_package_activation (
                package_id, vertical_id, available, enabled, previously_enabled,
                availability_reasons, package_version, image_digest,
                asset_manifest_digest, semantic_profile_digest, revision,
                effective_at, ontology_release_id, ontology_release_digest,
                source_authority
            ) VALUES (
                'cost-governance', 'cost-governance', TRUE, FALSE, FALSE,
                '[]'::JSONB, '0.1.1', %s, %s, %s, 1, NOW(),
                'ontology-release:legacy', %s, 'legacy-test'
            )
            """,
            (_digest("a"), _digest("b"), _digest("c"), _digest("d")),
        )
        connection.execute(
            "SELECT * FROM fdai_set_cost_governance_enabled(%s, %s, %s, %s, %s)",
            (
                "cost-governance",
                "operator-owner",
                True,
                1,
                "legacy-enable-request-0001",
            ),
        ).fetchone()
        connection.execute(_migration_sql(_LIFECYCLE_REPAIR_MIGRATION, "upgrade")[1])

    receipts = await PostgresCostGovernanceValidationStore(
        dsn=disposable_database_url
    ).read_cost_lifecycle_receipts("cost-governance", limit=10)
    with psycopg.connect(disposable_database_url) as connection:
        retained = connection.execute(
            "SELECT count(*) FROM cost_governance_lifecycle_receipt"
        ).fetchone()

    assert receipts == ()
    assert retained == (1,)


async def test_campaign_retention_uses_grace_and_legal_hold_before_tombstone(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        for path in (_RUNTIME_MIGRATION, _MIGRATION):
            connection.execute(_migration_sql(path, "upgrade")[1])
    observed_at = datetime(2026, 9, 12, tzinfo=UTC)
    episode = CostCampaignEpisode(
        schema_version="1.0.0",
        campaign_id="campaign-retention",
        episode_id="episode-retention",
        revision=1,
        idempotency_key="episode:retention",
        revision_pin_digest=_digest("a"),
        evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
        outcome=CostCampaignOutcome.NO_OP,
        reason="verified.no-op",
        target_refs=("remediate.right-size",),
        settlement_statuses=(CostCampaignSettlement.VERIFIED,),
        recovery_attempts=0,
        policy_excluded=False,
        policy_escape=False,
        objective_regression=False,
        audit_complete=True,
        hard_dependencies_complete=True,
        unauthorized_disclosure=False,
        ontology_competency_passed=True,
        topic_owner_correct=True,
        protected_objectives_complete=True,
        safeguards_complete=True,
        effect_path_complete=True,
        parity_explained=True,
        rollback_evidence_complete=True,
        decision_correct=True,
        observed_at=observed_at,
        evidence_refs=("audit:retention",),
        retention_until=observed_at + timedelta(days=400),
    )
    store = PostgresCostGovernanceValidationStore(dsn=disposable_database_url)

    assert await store.append_cost_campaign_episode(episode, expected_revision=0)
    assert await store.set_validation_legal_hold(
        evidence_kind="campaign-episode",
        evidence_id=episode.episode_id,
        expected_revision=1,
        legal_hold_ref="legal-hold:campaign-retention",
        recorded_at=observed_at + timedelta(days=1),
        idempotency_key="hold:campaign-retention",
    )
    assert (
        await store.purge_validation_evidence(
            now=observed_at + timedelta(days=431),
            limit=10,
        )
        == ()
    )
    assert await store.set_validation_legal_hold(
        evidence_kind="campaign-episode",
        evidence_id=episode.episode_id,
        expected_revision=2,
        legal_hold_ref=None,
        recorded_at=observed_at + timedelta(days=2),
        idempotency_key="release:campaign-retention",
    )
    assert await store.purge_validation_evidence(
        now=observed_at + timedelta(days=431),
        limit=10,
    ) == (("campaign-episode", episode.episode_id),)

    with psycopg.connect(disposable_database_url) as connection:
        retention = connection.execute(
            """
            SELECT revision, retention_until, purge_after, legal_hold, purged_at
              FROM cost_governance_validation_retention
             WHERE evidence_kind = 'campaign-episode' AND evidence_id = %s
            """,
            (episode.episode_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM cost_governance_campaign_episode WHERE episode_id = %s",
            (episode.episode_id,),
        ).fetchone()
    assert retention is not None
    assert retention[0] == 4
    assert retention[2] - retention[1] == timedelta(days=30)
    assert retention[3] is False
    assert retention[4] is not None
    assert receipt_count == (1,)


def test_w7_migration_has_explicit_reverse_path() -> None:
    _, downgrade = _sql("downgrade")

    assert "DROP TABLE cost_governance_validation_retention_event" in downgrade
    assert "DROP TABLE cost_governance_validation_retention" in downgrade
    assert "DROP TABLE cost_governance_campaign_episode" in downgrade
    assert "DROP TABLE cost_governance_lifecycle_receipt" in downgrade
