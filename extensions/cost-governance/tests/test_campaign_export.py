from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

import fdai_cost_governance.campaign_export as campaign_export
from fdai_cost_governance.campaign_export import (
    CostReleaseQualification,
    NoCompleteCostObservationsError,
    PostgresCostCampaignObservationSource,
    _bounded_text_set,
    _bounded_text_tuple,
    _mapping,
    _normalize_gate_observation,
    _normalize_observation,
    _outcome_kind,
    _parser,
    _protected_objectives_complete,
    _recovery_attempts,
    _required_text,
    _run,
    _same_action_id,
    _string_list,
    _timestamp,
    export_cost_campaign_batch,
    load_cost_release_qualification,
    main,
)
from fdai_cost_governance.campaign_import import _canonical_digest

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_ACTION_ID = "00000000-0000-0000-0000-000000000001"


def _qualification() -> CostReleaseQualification:
    return CostReleaseQualification(
        source_revision="a" * 40,
        revision_pin_digest=f"sha256:{'b' * 64}",
        ontology_competency_passed=True,
        parity_explained=True,
        evidence_refs=(f"sha256:{'c' * 64}", f"sha256:{'d' * 64}"),
        digest=f"sha256:{'e' * 64}",
    )


def _row() -> dict[str, object]:
    expected = {
        "prediction_id": "prediction-001",
        "metric": "monthly-cost",
        "expected_min": 0,
        "expected_max": 100,
        "predicted_at": "2026-09-11T00:00:00+00:00",
        "observation_deadline": "2026-09-13T00:00:00+00:00",
    }
    return {
        "outcome_seq": 14,
        "outcome_created_at": _NOW,
        "outcome_entry": {
            "action_id": _ACTION_ID,
            "action_type_id": "remediate.right-size",
            "actor": "fdai.measurement",
            "decision": "auto",
            "evidence_refs": ["effect:prediction-001"],
            "execution_mode": "shadow",
            "execution_outcome": "published",
            "label": "verified",
            "observed_at": "2026-09-12T00:00:00+00:00",
            "verification_passed": True,
            "verification_reason": "value_within_expected_range",
            **expected,
        },
        "risk_seq": 11,
        "risk_entry": {
            "action_id": _ACTION_ID,
            "decision": "shadow",
            "producer_principal": "Forseti",
            "authority": {"ceiling_inputs": {"system_degraded": False}},
        },
        "intent_seq": 12,
        "intent_entry": {
            "action_id": _ACTION_ID,
            "dry_run_passed": True,
            "dry_run_receipt": "dry-run:001",
            "idempotency_key": "action:001",
        },
        "terminal_seq": 13,
        "terminal_entry": {
            "action_id": _ACTION_ID,
            "action_kind": "remediate.right-size",
            "actor": "fdai.core.executor.shadow",
            "blast_radius": {"scope": "resource", "count": 1},
            "dry_run_receipt": "dry-run:001",
            "idempotency_key": "action:001",
            "rollback_kind": "pr_revert",
            "rollback_reference": "pr-1",
            "safeguard_bundle_digest": f"sha256:{'a' * 64}",
            "stop_condition": "provider_api_error_streak",
        },
        "workflow_ref": "cost-aware-remediation",
        "plan_entry": {
            "proposal": {"plan": {"plan_id": "prediction-001"}},
            "operational_plan": {
                "complete": True,
                "selection": {"selected_option_id": "option-001"},
                "decision_case": {
                    "protected_objective_ids": ["service-objective-001"],
                    "options": [
                        {
                            "option_id": "option-001",
                            "action_type": "remediate.right-size",
                            "effects": [
                                {
                                    "objective_id": "service-objective-001",
                                    "metric": "monthly-cost",
                                    "expected_min": 0,
                                    "expected_max": 100,
                                }
                            ],
                        }
                    ],
                },
            },
        },
    }


def test_normalization_requires_complete_lineage_and_preserves_workflow_target() -> None:
    observation = _normalize_observation(
        _row(),
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    assert observation["target_refs"] == [
        "remediate.right-size",
        "cost-aware-remediation",
    ]
    assert observation["outcome"] == "no-op"
    assert observation["settlement_statuses"] == ["verified"]
    assert observation["policy_escape"] is False
    assert observation["decision_correct"] is True
    assert observation["safeguards_complete"] is True
    assert observation["hard_dependencies_complete"] is True
    assert observation["protected_objectives_complete"] is True
    assert observation["ontology_competency_passed"] is True
    assert observation["parity_explained"] is True
    assert observation["unauthorized_disclosure"] is False


def test_policy_mismatch_and_missing_safeguard_fail_closed() -> None:
    row = _row()
    row["risk_entry"] = {**row["risk_entry"], "decision": "deny"}  # type: ignore[dict-item]
    row["intent_entry"] = {**row["intent_entry"], "dry_run_passed": False}  # type: ignore[dict-item]

    observation = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=True,
    )

    assert observation["policy_escape"] is True
    assert observation["decision_correct"] is False
    assert observation["safeguards_complete"] is False
    assert observation["unauthorized_disclosure"] is True
    assert observation["target_refs"] == ["remediate.right-size"]


def test_enforce_effect_settlement_is_separate_from_policy_escape() -> None:
    row = _row()
    row["risk_entry"] = {**row["risk_entry"], "decision": "auto"}  # type: ignore[dict-item]
    row["outcome_entry"] = {  # type: ignore[dict-item]
        **row["outcome_entry"],  # type: ignore[misc]
        "execution_mode": "enforce",
    }
    row["terminal_entry"] = {  # type: ignore[dict-item]
        **row["terminal_entry"],  # type: ignore[misc]
        "workflow_action": {
            "process_id": "process-001",
            "step_id": "apply_rightsize",
            "proposal_ref": "proposal-001",
            "attempt": 3,
        },
    }

    beneficial = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert beneficial["outcome"] == "beneficial-action"
    assert beneficial["policy_escape"] is False
    assert beneficial["recovery_attempts"] == 2

    row["outcome_entry"] = {  # type: ignore[dict-item]
        **row["outcome_entry"],  # type: ignore[misc]
        "decision": "abstain",
        "label": "mismatch",
        "verification_passed": False,
    }
    mismatch = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert mismatch["outcome"] == "execute"
    assert mismatch["policy_escape"] is False
    assert mismatch["objective_regression"] is True
    assert mismatch["decision_correct"] is False


def test_missing_plan_lineage_blocks_protected_objective_claim() -> None:
    row = _row()
    row["plan_entry"] = None

    observation = _normalize_observation(
        row,
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    assert observation["protected_objectives_complete"] is False


def test_release_qualification_is_digest_and_active_pin_bound(tmp_path: Path) -> None:
    body = {
        "evidence_refs": [f"sha256:{'c' * 64}", f"sha256:{'d' * 64}"],
        "ontology_competency_passed": True,
        "parity_explained": True,
        "revision_pin_digest": f"sha256:{'b' * 64}",
        "schema_version": "1.0.0",
        "source_revision": "a" * 40,
    }
    path = tmp_path / "qualification.json"
    path.write_text(
        json.dumps({**body, "qualification_digest": _canonical_digest(body)}),
        encoding="utf-8",
    )

    qualification = load_cost_release_qualification(
        path,
        source_revision="a" * 40,
        revision_pin_digest=f"sha256:{'b' * 64}",
    )

    assert qualification.ontology_competency_passed is True
    with pytest.raises(ValueError, match="active release"):
        load_cost_release_qualification(
            path,
            source_revision="e" * 40,
            revision_pin_digest=f"sha256:{'b' * 64}",
        )


def test_export_batch_is_canonical_and_rejects_empty_cohort() -> None:
    observation = _normalize_observation(
        _row(),
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    batch = export_cost_campaign_batch(
        campaign_id="campaign-001",
        revision_pin_digest=f"sha256:{'a' * 64}",
        observations=(observation,),
    )
    body = {key: value for key, value in batch.items() if key != "batch_digest"}

    assert batch["batch_digest"] == _canonical_digest(body)

    try:
        export_cost_campaign_batch(
            campaign_id="campaign-001",
            revision_pin_digest=f"sha256:{'a' * 64}",
            observations=(),
        )
    except NoCompleteCostObservationsError:
        pass
    else:
        raise AssertionError("empty campaign export must use the bounded no-data outcome")


def test_campaign_export_helpers_and_gate_observations(tmp_path: Path) -> None:
    gate_row: dict[str, object] = {
        "risk_seq": 21,
        "risk_created_at": _NOW,
        "risk_entry": {
            "action_id": _ACTION_ID,
            "action_type_id": "remediate.right-size",
            "decision": "deny",
            "gate_reasons": ["policy_blocked"],
            "producer_principal": "Forseti",
            "authority": {
                "ceiling_inputs": {
                    "system_degraded": False,
                    "kill_switch_engaged": False,
                }
            },
        },
        "workflow_ref": "cost-aware-remediation",
        "plan_entry": _row()["plan_entry"],
    }
    obs_deny = _normalize_gate_observation(
        gate_row,
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert obs_deny["outcome"] == "deny"
    assert obs_deny["reason"] == "gate.policy_blocked"
    assert obs_deny["hard_dependencies_complete"] is True
    assert obs_deny["protected_objectives_complete"] is True

    gate_row_hil = {
        **gate_row,
        "risk_entry": {
            **gate_row["risk_entry"],  # type: ignore[misc]
            "decision": "hil",
            "gate_reasons": [],
        },
        "workflow_ref": "other",
    }
    obs_hil = _normalize_gate_observation(
        gate_row_hil,
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=True,
    )
    assert obs_hil["outcome"] == "approval"
    assert obs_hil["reason"] == "gate.hil"

    with pytest.raises(ValueError, match="MUST be deny or hil"):
        _normalize_gate_observation(
            {**gate_row, "risk_entry": {**gate_row["risk_entry"], "decision": "auto"}},  # type: ignore[misc]
            workflow_ids=frozenset(),
            qualification=_qualification(),
            unauthorized_disclosure=False,
        )
    with pytest.raises(ValueError, match="observation time is unavailable"):
        _normalize_gate_observation(
            {**gate_row, "risk_created_at": "bad"},
            workflow_ids=frozenset(),
            qualification=_qualification(),
            unauthorized_disclosure=False,
        )

    row_fallback = _row()
    row_fallback["outcome_entry"] = {
        k: v
        for k, v in row_fallback["outcome_entry"].items()  # type: ignore[union-attr]
        if k != "observed_at"
    }
    obs_fb = _normalize_observation(
        row_fallback,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert obs_fb["observed_at"] == _NOW.isoformat()

    row_no_time = {**row_fallback, "outcome_created_at": "invalid"}
    with pytest.raises(ValueError, match="observation time is unavailable"):
        _normalize_observation(
            row_no_time,
            workflow_ids=frozenset(),
            qualification=_qualification(),
            unauthorized_disclosure=False,
        )

    row_bad_kind = _row()
    row_bad_kind["terminal_entry"] = {
        **row_bad_kind["terminal_entry"],  # type: ignore[misc]
        "action_kind": "other.action",
    }
    with pytest.raises(ValueError, match="does not match outcome"):
        _normalize_observation(
            row_bad_kind,
            workflow_ids=frozenset(),
            qualification=_qualification(),
            unauthorized_disclosure=False,
        )

    with pytest.raises(ValueError, match="mixed action identity"):
        _same_action_id({"action_id": "a1"}, {"action_id": "a2"})
    for (r_dec, ex_mode, ex_out, r_ok), exp_kind in (
        (("auto", "enforce", "ok", True), "rollback"),
        (("hil", "shadow", "ok", False), "approval"),
        (("deny", "shadow", "ok", False), "deny"),
        (("auto", "enforce", "failed_dispatch", False), "hold-unresolved"),
    ):
        assert (
            _outcome_kind(
                risk_decision=r_dec,
                execution_mode=ex_mode,
                execution_outcome=ex_out,
                settlement_label="verified",
                rollback_succeeded=r_ok,
            )
            == exp_kind
        )
    with pytest.raises(ValueError, match="recovery attempt"):
        _recovery_attempts({"workflow_action": {"attempt": 0}}, rollback=False)
    with pytest.raises(ValueError, match="MUST be an object"):
        _mapping("bad", "risk")
    with pytest.raises(ValueError, match="bounded non-empty ASCII"):
        _required_text({"k": ""}, "k")
    with pytest.raises(ValueError, match="bounded ASCII array"):
        _string_list([""], "refs")
    with pytest.raises(ValueError, match="RFC3339"):
        _timestamp("bad")
    with pytest.raises(ValueError, match="include a timezone"):
        _timestamp("2026-09-12T00:00:00")
    assert _bounded_text_set("not-list", maximum=4) == set()
    assert _bounded_text_set([""], maximum=4) == set()
    with pytest.raises(ValueError, match="bounded array"):
        _bounded_text_tuple([], maximum=4)
    with pytest.raises(ValueError, match="bounded ASCII"):
        _bounded_text_tuple([""], maximum=4)
    with pytest.raises(ValueError, match="MUST be unique"):
        _bounded_text_tuple(["a", "a"], maximum=4)

    plan_base = _row()["plan_entry"]

    def _plan_with_effects(effects: list[object]) -> dict[str, object]:
        return {
            **plan_base,  # type: ignore[misc]
            "operational_plan": {
                "complete": True,
                "selection": {"selected_option_id": "option-001"},
                "decision_case": {
                    "protected_objective_ids": ["obj-1"],
                    "options": [
                        {
                            "option_id": "option-001",
                            "action_type": "remediate.right-size",
                            "effects": effects,
                        }
                    ],
                },
            },
        }

    for invalid_plan in (
        {"operational_plan": {"complete": False}},
        {"operational_plan": {"complete": True}},
        {
            **plan_base,  # type: ignore[misc]
            "operational_plan": {
                **plan_base["operational_plan"],  # type: ignore[index]
                "selection": {"selected_option_id": "missing"},
            },
        },
        _plan_with_effects([]),
        _plan_with_effects(["not-a-dict"]),
        _plan_with_effects([{"objective_id": 1, "metric": "m"}]),
        _plan_with_effects([{"objective_id": "obj-1", "metric": "m", "expected_min": None}]),
    ):
        assert not _protected_objectives_complete(
            invalid_plan,
            action_type_id="remediate.right-size",
            outcome=None,
        )

    with pytest.raises(ValueError, match="unavailable or too large"):
        load_cost_release_qualification(
            tmp_path / "missing.json",
            source_revision="a" * 40,
            revision_pin_digest=f"sha256:{'b' * 64}",
        )
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="is invalid"):
        load_cost_release_qualification(
            bad_json,
            source_revision="a" * 40,
            revision_pin_digest=f"sha256:{'b' * 64}",
        )
    bad_fields = tmp_path / "fields.json"
    bad_fields.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fields are invalid"):
        load_cost_release_qualification(
            bad_fields,
            source_revision="a" * 40,
            revision_pin_digest=f"sha256:{'b' * 64}",
        )
    for override, match in (
        ({"ontology_competency_passed": "yes"}, "MUST be boolean"),
        ({"evidence_refs": ["not-a-sha"]}, "SHA-256 digests"),
    ):
        body = {
            "evidence_refs": [f"sha256:{'c' * 64}"],
            "ontology_competency_passed": True,
            "parity_explained": True,
            "revision_pin_digest": f"sha256:{'b' * 64}",
            "schema_version": "1.0.0",
            "source_revision": "a" * 40,
            **override,
        }
        p = tmp_path / "override.json"
        p.write_text(
            json.dumps({**body, "qualification_digest": _canonical_digest(body)}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=match):
            load_cost_release_qualification(
                p,
                source_revision="a" * 40,
                revision_pin_digest=f"sha256:{'b' * 64}",
            )


async def test_postgres_source_and_run_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="DSNs MUST be configured"):
        PostgresCostCampaignObservationSource(dsn="", operator_dsn="")

    src = PostgresCostCampaignObservationSource(
        dsn="postgresql+psycopg://localhost/core",
        operator_dsn="postgresql+psycopg://localhost/op",
    )
    with pytest.raises(ValueError, match="window MUST be positive"):
        await src.observations(
            start_at=_NOW,
            end_at=_NOW,
            action_type_ids=("remediate.right-size",),
            workflow_ids=frozenset(),
            qualification=_qualification(),
            maximum_episodes=10,
        )
    with pytest.raises(ValueError, match="episode bound"):
        await src.observations(
            start_at=_NOW,
            end_at=_NOW + timedelta(hours=1),
            action_type_ids=("remediate.right-size",),
            workflow_ids=frozenset(),
            qualification=_qualification(),
            maximum_episodes=0,
        )

    state: dict[str, Any] = {
        "disclosure": {"delivered_count": 1, "unauthorized_count": 0},
        "rows": [_row()],
        "gate_rows": [],
    }

    class _FakeCursor:
        def __init__(self, one: Any = None, many: Any = ()) -> None:
            self._one = one
            self._many = many

        async def fetchone(self) -> Any:
            return self._one

        async def fetchall(self) -> Any:
            return self._many

    class _FakeConn:
        async def __aenter__(self) -> _FakeConn:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
            if "FROM cost_disclosure_audit" in sql:
                return _FakeCursor(one=state["disclosure"])
            if "WITH outcomes AS" in sql:
                return _FakeCursor(many=state["rows"])
            if "WITH decisions AS" in sql:
                return _FakeCursor(many=state["gate_rows"])
            return _FakeCursor()

    async def _fake_connect(*args: Any, **kwargs: Any) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _fake_connect)
    obs = await src.observations(
        start_at=_NOW - timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1),
        action_type_ids=("remediate.right-size",),
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        maximum_episodes=10,
    )
    assert len(obs) == 1

    state["disclosure"] = None
    with pytest.raises(RuntimeError, match="coverage is unavailable"):
        await src.observations(
            start_at=_NOW - timedelta(hours=1),
            end_at=_NOW + timedelta(hours=1),
            action_type_ids=("remediate.right-size",),
            workflow_ids=frozenset(),
            qualification=_qualification(),
            maximum_episodes=10,
        )

    state["disclosure"] = {"delivered_count": 0, "unauthorized_count": 0}
    with pytest.raises(NoCompleteCostObservationsError):
        await src.observations(
            start_at=_NOW - timedelta(hours=1),
            end_at=_NOW + timedelta(hours=1),
            action_type_ids=("remediate.right-size",),
            workflow_ids=frozenset(),
            qualification=_qualification(),
            maximum_episodes=10,
        )

    parser = _parser()
    base_argv = [
        "--campaign-id",
        "campaign-001",
        "--start-at",
        "2026-09-12T00:00:00Z",
        "--end-at",
        "2026-09-12T02:00:00Z",
        "--catalog-root",
        str(tmp_path),
        "--qualification",
        str(tmp_path / "q.json"),
        "--policy",
        str(tmp_path / "p.json"),
        "--output",
        str(tmp_path / "out.json"),
    ]
    args = parser.parse_args(base_argv)
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    with pytest.raises(ValueError, match="MUST be configured"):
        await _run(args)

    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost/core")
    monkeypatch.setenv("FDAI_OPERATOR_STORE_DSN", "postgresql://localhost/op")

    from types import SimpleNamespace

    import fdai_cost_governance.validation_cli as validation_cli

    act_box: dict[str, Any] = {
        "enabled": False,
        "effective_at": _NOW + timedelta(hours=5),
    }

    async def _fake_read_act(dsn: str) -> tuple[Any, bool, datetime]:
        return (
            SimpleNamespace(source_revision="a" * 40, digest=f"sha256:{'b' * 64}"),
            act_box["enabled"],
            act_box["effective_at"],
        )

    monkeypatch.setattr(validation_cli, "read_current_activation", _fake_read_act)
    with pytest.raises(ValueError, match="MUST be enabled"):
        await _run(args)

    act_box["enabled"] = True
    with pytest.raises(NoCompleteCostObservationsError, match="predates the active release"):
        await _run(args)

    act_box["effective_at"] = _NOW - timedelta(hours=1)
    monkeypatch.setattr(
        campaign_export,
        "load_cost_release_qualification",
        lambda path, **kw: _qualification(),
    )
    monkeypatch.setattr(
        campaign_export,
        "load_cost_campaign_import_policy",
        lambda path: SimpleNamespace(maximum_batch_episodes=10),
    )
    from fdai_cost_governance.validation import CostReadinessTargetKind

    monkeypatch.setattr(
        campaign_export,
        "load_cost_readiness_targets",
        lambda root: (
            SimpleNamespace(
                target_id="remediate.right-size",
                kind=CostReadinessTargetKind.ACTION_TYPE,
            ),
            SimpleNamespace(
                target_id="cost-aware-remediation",
                kind=CostReadinessTargetKind.WORKFLOW,
            ),
        ),
    )
    state["disclosure"] = {"delivered_count": 1, "unauthorized_count": 0}
    exported = await _run(args)
    assert exported["campaign_id"] == "campaign-001"


def test_campaign_export_cli_main_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_file = tmp_path / "out.json"
    argv = [
        "--campaign-id",
        "c1",
        "--start-at",
        "2026-09-12T00:00:00Z",
        "--end-at",
        "2026-09-12T02:00:00Z",
        "--catalog-root",
        str(tmp_path),
        "--qualification",
        str(tmp_path / "q.json"),
        "--policy",
        str(tmp_path / "p.json"),
        "--output",
        str(out_file),
    ]
    parser = _parser()
    parsed = parser.parse_args(argv)
    assert parsed.campaign_id == "c1"

    async def _ok_run(args: Any) -> dict[str, object]:
        return {"campaign_id": "c1"}

    monkeypatch.setattr(campaign_export, "_run", _ok_run)
    assert main(argv) == 0
    assert json.loads(out_file.read_text(encoding="utf-8")) == {"campaign_id": "c1"}

    async def _no_obs_run(args: Any) -> dict[str, object]:
        raise NoCompleteCostObservationsError("none")

    monkeypatch.setattr(campaign_export, "_run", _no_obs_run)
    assert main(argv) == 3

    async def _err_run(args: Any) -> dict[str, object]:
        raise ValueError("bad")

    monkeypatch.setattr(campaign_export, "_run", _err_run)
    assert main(argv) == 2
