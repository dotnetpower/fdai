from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
)
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)

import fdai_cost_governance.validation_cli as validation_cli
from fdai_cost_governance.review_targets import CostReadinessTarget
from fdai_cost_governance.validation import (
    CostReadinessTargetKind,
    CostReadinessThresholds,
)
from fdai_cost_governance.validation_cli import (
    _parser,
    _psycopg_dsn,
    _run,
    _timestamp,
    evaluate_cost_campaign,
    main,
    read_current_activation,
    read_current_pin,
)

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_ACTION = "remediate.right-size"
_WORKFLOW = "cost-aware-remediation"


def _pin(revision: int = 5) -> CostRevisionPin:
    return CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="a" * 40,
        wheel_digest=f"sha256:{'b' * 64}",
        image_digest=f"sha256:{'c' * 64}",
        asset_manifest_digest=f"sha256:{'d' * 64}",
        semantic_profile_digest=f"sha256:{'e' * 64}",
        ontology_release_digest=f"sha256:{'f' * 64}",
        runtime_config_digest=f"sha256:{'0' * 64}",
        activation_revision=revision,
    )


def _receipt(operation: CostLifecycleOperation, revision: int) -> CostLifecycleReceipt:
    return CostLifecycleReceipt(
        schema_version="1.0.0",
        receipt_id=f"receipt:{operation.value}:{revision}",
        idempotency_key=f"receipt:{operation.value}:{revision}",
        operation=operation,
        outcome=CostLifecycleOutcome.SUCCEEDED,
        revision_pin=_pin(revision),
        available=True,
        enabled=operation not in {CostLifecycleOperation.INSTALL, CostLifecycleOperation.DISABLE},
        occurred_at=_NOW + timedelta(minutes=revision),
        evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
        evidence_refs=(f"evidence:{operation.value}",),
        retention_until=_NOW + timedelta(days=400),
    )


def _receipts() -> tuple[CostLifecycleReceipt, ...]:
    return tuple(
        _receipt(operation, revision)
        for revision, operation in enumerate(CostLifecycleOperation, start=1)
    )


def _episode(
    episode_id: str,
    *,
    target_refs: tuple[str, ...],
    observed_at: datetime,
    outcome: CostCampaignOutcome,
) -> CostCampaignEpisode:
    return CostCampaignEpisode(
        schema_version="1.0.0",
        campaign_id="campaign-001",
        episode_id=episode_id,
        revision=1,
        idempotency_key=f"episode:{episode_id}",
        revision_pin_digest=_pin().digest,
        evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
        outcome=outcome,
        reason="verified.outcome",
        target_refs=target_refs,
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
        evidence_refs=(f"evidence:{episode_id}",),
        retention_until=_NOW + timedelta(days=400),
    )


def _target(kind: CostReadinessTargetKind, target_id: str) -> CostReadinessTarget:
    return CostReadinessTarget(
        kind=kind,
        target_id=target_id,
        thresholds=CostReadinessThresholds(2, 86_400, Decimal("1")),
    )


def test_evaluation_is_separate_and_blocks_missing_target_evidence() -> None:
    episodes = (
        _episode(
            "action-first",
            target_refs=(_ACTION,),
            observed_at=_NOW,
            outcome=CostCampaignOutcome.NO_OP,
        ),
        _episode(
            "action-second",
            target_refs=(_ACTION,),
            observed_at=_NOW + timedelta(days=1),
            outcome=CostCampaignOutcome.ROLLBACK,
        ),
    )
    targets = (
        _target(CostReadinessTargetKind.PACKAGE_ACTIVATION, "cost-governance"),
        _target(CostReadinessTargetKind.ACTION_TYPE, _ACTION),
        _target(CostReadinessTargetKind.WORKFLOW, _WORKFLOW),
    )

    result = evaluate_cost_campaign(
        campaign_id="campaign-001",
        revision_pin=_pin(),
        lifecycle_receipts=_receipts(),
        episodes=episodes,
        targets=targets,
    )

    assert result["ready"] is False
    assert set(result) == {
        "campaign_id",
        "ready",
        "revision_pin_digest",
        "targets",
    }
    records = {item["target_id"]: item for item in result["targets"]}
    assert records["cost-governance"]["decision"] == "ready-for-independent-review"
    assert records[_ACTION]["decision"] == "ready-for-independent-review"
    assert records[_WORKFLOW]["decision"] == "blocked"
    assert records[_WORKFLOW]["sample_count"] == 0


async def test_validation_cli_helpers_and_commands(
    monkeypatch,
    tmp_path,
) -> None:
    import psycopg
    import pytest

    assert _psycopg_dsn("postgresql+psycopg://localhost/db") == "postgresql://localhost/db"
    assert _timestamp("2026-09-12T01:02:03Z") == datetime(2026, 9, 12, 1, 2, 3, tzinfo=UTC)
    with pytest.raises(ValueError, match="MUST be RFC3339"):
        _timestamp("not-a-timestamp")
    with pytest.raises(ValueError, match="MUST include a timezone"):
        _timestamp("2026-09-12T01:02:03")

    row_box: dict[str, object | None] = {
        "row": {
            "package_id": "cost-governance",
            "package_version": "0.1.1",
            "source_revision": "a" * 40,
            "wheel_digest": f"sha256:{'b' * 64}",
            "image_digest": f"sha256:{'c' * 64}",
            "asset_manifest_digest": f"sha256:{'d' * 64}",
            "semantic_profile_digest": f"sha256:{'e' * 64}",
            "ontology_release_digest": f"sha256:{'f' * 64}",
            "runtime_config_digest": f"sha256:{'0' * 64}",
            "revision": 5,
            "available": True,
            "enabled": True,
            "effective_at": _NOW,
        }
    }

    class _FakeCursor:
        async def fetchone(self):
            return row_box["row"]

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, *args, **kwargs):
            return _FakeCursor()

    async def _fake_connect(*args, **kwargs):
        return _FakeConn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _fake_connect)
    pin, enabled = await read_current_pin("postgresql+psycopg://localhost/db")
    assert enabled is True
    assert pin.activation_revision == 5

    orig_row = dict(row_box["row"])  # type: ignore[arg-type]
    row_box["row"] = None
    with pytest.raises(ValueError, match="unavailable"):
        await read_current_activation("postgresql://localhost/db")

    row_box["row"] = {**orig_row, "wheel_digest": "invalid"}
    with pytest.raises(ValueError, match="pin is incomplete"):
        await read_current_activation("postgresql://localhost/db")

    row_box["row"] = {**orig_row, "effective_at": "not-a-dt"}
    with pytest.raises(ValueError, match="effective time is incomplete"):
        await read_current_activation("postgresql://localhost/db")

    row_box["row"] = orig_row
    parser = _parser()
    with pytest.raises(ValueError, match="FDAI_STATE_STORE_DSN MUST be configured"):
        await _run(parser.parse_args(["pin"]), {})

    code, pin_out = await _run(
        parser.parse_args(["pin"]),
        {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
    )
    assert code == 0
    assert pin_out["enabled"] is True

    row_box["row"] = {**orig_row, "enabled": False}
    with pytest.raises(ValueError, match="MUST be enabled"):
        await _run(
            parser.parse_args(["evaluate", "--campaign-id", "c1", "--catalog-root", str(tmp_path)]),
            {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
        )

    row_box["row"] = orig_row
    targets = (
        _target(CostReadinessTargetKind.PACKAGE_ACTIVATION, "cost-governance"),
        _target(CostReadinessTargetKind.ACTION_TYPE, _ACTION),
    )
    monkeypatch.setattr(validation_cli, "load_cost_readiness_targets", lambda root: targets)

    class _FakeStore:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        async def read_cost_lifecycle_receipts(self, package_id: str, limit: int):
            return _receipts()

        async def read_cost_campaign_episodes(self, campaign_id: str, digest: str, limit: int):
            return ()

    monkeypatch.setattr(validation_cli, "PostgresCostGovernanceValidationStore", _FakeStore)
    monkeypatch.setattr(validation_cli, "load_cost_campaign_import_policy", lambda p: _FakePolicy())
    monkeypatch.setattr(
        validation_cli,
        "load_cost_campaign_observation_batch",
        lambda p, maximum_episodes: (),
    )

    async def _fake_import(*args, **kwargs):
        return _FakeReport()

    monkeypatch.setattr(validation_cli, "import_cost_campaign_observations", _fake_import)

    import_args = parser.parse_args(
        [
            "import",
            "--batch",
            str(tmp_path / "b.json"),
            "--policy",
            str(tmp_path / "p.json"),
            "--catalog-root",
            str(tmp_path),
            "--source-workflow-path",
            ".github/workflows/w.yml",
            "--source-run-id",
            "1",
            "--source-run-attempt",
            "1",
            "--source-artifact-name",
            "cost-governance-observations-run-1",
            "--imported-at",
            "2026-09-12T00:00:00Z",
        ]
    )
    code_imp, imp_out = await _run(
        import_args,
        {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
    )
    assert code_imp == 0
    assert imp_out == {"imported": True}

    eval_args = parser.parse_args(
        ["evaluate", "--campaign-id", "c1", "--catalog-root", str(tmp_path), "--require-ready"]
    )
    code_eval, _ = await _run(
        eval_args,
        {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
    )
    assert code_eval == 3


def test_validation_cli_main_sync(monkeypatch) -> None:
    import psycopg

    async def _fake_run(args, env):
        if not env.get("FDAI_STATE_STORE_DSN"):
            raise ValueError("missing dsn")
        return 0, {"ok": True}

    monkeypatch.setattr(validation_cli, "_run", _fake_run)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost/db")
    assert main(["pin"]) == 0

    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    assert main(["pin"]) == 2

    async def _raise_pg(args, env):
        raise psycopg.OperationalError("boom")

    monkeypatch.setattr(validation_cli, "_run", _raise_pg)
    assert main(["pin"]) == 2


class _FakePolicy:
    maximum_batch_episodes = 10


class _FakeReport:
    def to_mapping(self) -> dict[str, object]:
        return {"imported": True}
