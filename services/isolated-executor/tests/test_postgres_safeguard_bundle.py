"""Production PostgreSQL safeguard-bundle resolver tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

import psycopg
import pytest
from fdai_executor_service.adapters.postgres_safeguard_bundle import (
    PostgresSafeguardBundleStore,
    PostgresSafeguardBundleStoreConfig,
)
from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor_models import ExecutionPath

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "service-migrations/branches/isolated-executor/versions/"
    "20260912_executor_safeguard_bundle_read.py"
)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql: str, params: object = None) -> _Cursor:
        self.calls.append((sql, params))
        return _Cursor(self._rows if "FROM safeguard_dispatch_evidence" in sql else [])

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _bundle() -> SafeguardProofBundle:
    return SafeguardProofBundle.create(
        action_id=UUID(int=1),
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="sha256:" + "a" * 64,
        source_revision="commit:" + "b" * 40,
        recorded_at=datetime(2026, 9, 11, tzinfo=UTC),
        proofs=tuple(
            SafeguardProof(
                kind=kind,
                proof_digest="sha256:" + f"{index:x}" * 64,
            )
            for index, kind in enumerate(SafeguardProofKind, start=1)
        ),
    )


def test_bundle_lookup_index_matches_runtime_json_path() -> None:
    migration = _MIGRATION.read_text(encoding="utf-8")

    assert "record #>> '{bundle,bundle_digest}'" in migration
    assert "record #>> '{{bundle,bundle_digest}}'" not in migration
    assert '"revision": "core_safeguard_dispatch_evidence_20260911"' in migration


async def test_postgres_bundle_store_reads_exact_core_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    connection = _Connection(
        [
            {
                "record": {
                    "bundle": bundle.model_dump(mode="json"),
                    "identity": {"reservation_attempt": 1},
                }
            }
        ]
    )

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    resolved = await store.resolve_bundle(bundle.bundle_digest)

    assert resolved == bundle
    query = next(sql for sql, _params in connection.calls if "FROM" in sql)
    assert "LIMIT 2" in query


async def test_postgres_bundle_store_rejects_ambiguous_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    row = {
        "record": {
            "bundle": bundle.model_dump(mode="json"),
            "identity": {"reservation_attempt": 1},
        }
    }
    connection = _Connection([row, row])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    with pytest.raises(RuntimeError, match="multiple generations"):
        await store.resolve_bundle(bundle.bundle_digest)


@pytest.mark.parametrize(
    ("dsn", "statement_timeout_ms", "connect_timeout_s", "match"),
    [
        ("", 15_000, 10, "dsn MUST NOT be empty"),
        ("postgresql://example", 0, 10, "timeouts MUST be positive"),
        ("postgresql://example", 15_000, 0, "timeouts MUST be positive"),
    ],
)
def test_postgres_bundle_store_config_validation(
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        PostgresSafeguardBundleStore(
            config=PostgresSafeguardBundleStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        )


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([{"record": "not-a-dict"}], "evidence is malformed"),
        ([{"record": {"bundle": None, "identity": {}}}], "proof bundle is missing"),
        (
            [{"record": {"bundle": {}, "identity": None}}],
            "evidence identity is missing",
        ),
        (
            [{"record": {"bundle": {}, "identity": {"reservation_attempt": True}}}],
            "reservation attempt is invalid",
        ),
        (
            [{"record": {"bundle": {}, "identity": {"reservation_attempt": 0}}}],
            "reservation attempt is invalid",
        ),
    ],
)
async def test_postgres_bundle_store_rejects_malformed_records(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    match: str,
) -> None:
    connection = _Connection(rows)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    with pytest.raises(ValueError, match=match):
        await store.resolve_bundle("sha256:" + "0" * 64)


async def test_postgres_bundle_store_handles_missing_and_mismatched_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    rows: list[dict[str, object]] = []
    connection = _Connection(rows)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    assert await store.resolve_bundle(bundle.bundle_digest) is None

    rows.append(
        {
            "record": {
                "bundle": bundle.model_dump(mode="json"),
                "identity": {"reservation_attempt": 1},
            }
        }
    )
    with pytest.raises(ValueError, match="digest mismatched"):
        await store.resolve_bundle("sha256:" + "f" * 64)


def test_bundle_validation_edge_cases() -> None:
    from datetime import timedelta

    from fdai_executor_service.bundle_validation import (
        BundleValidationRefusal,
        ResolvedSafeguardBundle,
        validate_bundle_binding_sync,
    )
    from fdai_service_contracts.executor_models import (
        Action,
        ActionStopCondition,
        BlastRadius,
        BlastRadiusScope,
        ExecutorCommand,
        Mode,
        Operation,
        RollbackKind,
        RollbackRef,
        SafeguardBoundExecutorCommand,
        StopConditionKind,
        executor_action_fingerprint,
    )

    now = datetime(2026, 9, 11, tzinfo=UTC)
    deadline = now + timedelta(seconds=60)
    bundle = _bundle()
    with pytest.raises(ValueError, match="requires an exact bundle"):
        ResolvedSafeguardBundle(bundle="bad", reservation_attempt=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST be positive"):
        ResolvedSafeguardBundle(bundle=bundle, reservation_attempt=0)
    refusal = BundleValidationRefusal("malformed", "bad")
    assert repr(refusal) == "BundleValidationRefusal('malformed', 'bad')"
    assert (
        validate_bundle_binding_sync(object(), bundle, now=now).category  # type: ignore[arg-type]
        == "malformed"
    )

    action = Action(
        schema_version="1.0.0",
        action_id=UUID(int=1),
        idempotency_key="bundle-edge",
        event_id=UUID(int=2),
        action_type="ops.start-vm",
        target_resource_ref=(
            "/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app"
        ),
        operation=Operation.ENABLE,
        params={"resource_group": "example", "vm_name": "vm-app"},
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=60)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["rule.example"],
        created_at=now,
    )
    v10 = ExecutorCommand.from_action(
        command_id=UUID(int=3),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now,
        deadline_at=deadline,
    )
    assert validate_bundle_binding_sync(v10, None, now=now) is None

    fingerprint = "sha256:" + executor_action_fingerprint(
        action_payload=action.model_dump(mode="json", exclude_none=False),
        execution_path=ExecutionPath.DIRECT_API.value,
    )
    matched_bundle = SafeguardProofBundle.create(
        action_id=action.action_id,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint=fingerprint,
        source_revision="commit:" + "b" * 40,
        recorded_at=now,
        proofs=bundle.proofs,
    )
    valid_cmd = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=4),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        safeguard_proof_bundle_digest=matched_bundle.bundle_digest,
        source_revision="commit:" + "b" * 40,
        attempt=1,
        issued_at=now,
        deadline_at=deadline,
    )
    bad_digest_cmd = valid_cmd.model_construct(
        **{**valid_cmd.__dict__, "safeguard_proof_bundle_digest": "invalid"}
    )
    res1 = validate_bundle_binding_sync(bad_digest_cmd, matched_bundle, now=now)
    assert res1 is not None and res1.category == "malformed"

    bad_payload_cmd = valid_cmd.model_construct(
        **{**valid_cmd.__dict__, "action_payload": {"invalid": True}}
    )
    res2 = validate_bundle_binding_sync(bad_payload_cmd, matched_bundle, now=now)
    assert res2 is not None and res2.category == "malformed"

    wrong_target_cmd = valid_cmd.model_construct(
        **{**valid_cmd.__dict__, "target_resource_ref": "other-target"}
    )
    res3 = validate_bundle_binding_sync(wrong_target_cmd, matched_bundle, now=now)
    assert res3 is not None and res3.category == "wrong-target"

    incomplete_proofs = matched_bundle.model_construct(**{**matched_bundle.__dict__, "proofs": ()})
    res4 = validate_bundle_binding_sync(valid_cmd, incomplete_proofs, now=now)
    assert res4 is not None and res4.category == "malformed"

    bad_authority = matched_bundle.model_construct(
        **{**matched_bundle.__dict__, "execution_authority": True}
    )
    res5 = validate_bundle_binding_sync(valid_cmd, bad_authority, now=now)
    assert res5 is not None and res5.category == "substituted"

    bad_verified = matched_bundle.model_construct(
        **{**matched_bundle.__dict__, "effect_verified": True}
    )
    res6 = validate_bundle_binding_sync(valid_cmd, bad_verified, now=now)
    assert res6 is not None and res6.category == "substituted"


async def test_postgres_human_access_source_unit_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import copy
    import runpy
    from datetime import timedelta

    from fdai_executor_service.adapters.postgres_human_access import (
        PostgresHumanAccessSource,
        _require_inverse_sources,
    )
    from fdai_service_contracts.human_access_execution import (
        HumanAccessCurrentEvidence,
        HumanAccessExecutionMaterial,
        HumanAccessPreparation,
        canonical_human_access_json,
        human_access_record_digest,
    )
    from fdai_service_contracts.human_access_recovery import (
        HumanAccessInverseBinding,
        mutation_evidence_digest,
    )

    support = runpy.run_path(
        str(
            Path(__file__).resolve().parents[3]
            / "packages/service-contracts/tests/test_human_access_execution.py"
        )
    )
    at, material_fn, evidence_fn = support["AT"], support["material"], support["evidence"]

    role_groups = {
        "Owner": "group:owner",
        "Approver": "group:approver",
        "Contributor": "group:contributor",
        "Reader": "group:reader",
    }
    rg_digest = human_access_record_digest(role_groups)

    base_mat = material_fn()
    case_id = base_mat.action().params["case_id"]
    orig_case = {
        "case_id": case_id,
        "revision": 5,
        "state": "ownership_merged",
        "intent": {
            "requested_role": base_mat.requested_role,
            "requester_ref": base_mat.requester_ref,
            "subject": {"provider": "entra", "subject_id": base_mat.subject_id},
        },
    }
    case_digest = human_access_record_digest(orig_case)
    promo = {"action_type": base_mat.action().action_type, "mode": "enforce", "revision": 1}
    promo_digest = human_access_record_digest(promo)

    mat = HumanAccessExecutionMaterial.model_validate(
        {
            **base_mat.model_dump(),
            "case_record_digest": case_digest,
            "role_groups_digest": rg_digest,
            "promotion_record_digest": promo_digest,
        }
    )
    prep = HumanAccessPreparation(
        material_digest=mat.digest,
        source_case_digest=case_digest,
        source_revision=5,
        prepared_revision=6,
    )
    decision_orig = {
        "approval_id": "approval:one",
        "idempotency_key": "k:1",
        "decision": "approve",
        "approver_oid": "person:reviewer-one",
        "decided_at": (at + timedelta(seconds=2)).isoformat(),
        "receipt_ref": "r:1",
    }
    ev_dump = evidence_fn(mat).model_dump()
    ev_dump["preparation_ref"] = prep.reference
    ev_dump["approvals"][0]["source_record_digest"] = human_access_record_digest(decision_orig)
    ev = HumanAccessCurrentEvidence.model_validate(ev_dump)
    active_case = {
        **orig_case,
        "revision": 6,
        "state": "iam_applying",
        "iam_preparation": prep.model_dump(mode="json"),
    }
    valid_payload: dict[str, object] = {
        "material": mat.model_dump(mode="json"),
        "kill_switch": {"engaged": False},
        "source_count": 2,
        "current": {"evidence": ev.model_dump(mode="json")},
        "case": active_case,
        "promotion": promo,
        "parks": {
            "approval:one": {
                "metadata": {
                    "decision_route": "human_access",
                    "material_digest": mat.digest,
                    "required_role": "Owner",
                    "target_subject_ref": mat.subject_id,
                },
                "submitter_oid": mat.requester_ref,
                "action": mat.action().model_dump(mode="json"),
                "approval_context": {"expires_at": mat.expires_at.isoformat()},
            }
        },
        "decisions": {"approval:one": decision_orig},
        "database_now": (at + timedelta(seconds=10)).isoformat(),
    }

    db_state: dict[str, object] = {
        "role": "fdai_executor",
        "source": copy.deepcopy(valid_payload),
    }

    class _FakeRowCursor:
        def __init__(self, row: object) -> None:
            self._row = row

        async def fetchone(self) -> object:
            return self._row

    class _FakeConn:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def execute(self, sql: str, _params: object = None) -> _FakeRowCursor:
            if "current_user" in sql:
                return _FakeRowCursor({"role": db_state["role"]} if db_state["role"] else None)
            if "fdai_executor_human_access_source" in sql:
                return _FakeRowCursor({"source": db_state["source"]})
            return _FakeRowCursor(None)

    async def fake_connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", fake_connect)
    src = PostgresHumanAccessSource("postgresql://example", role_groups)

    assert (
        await src.material_for(action_id=mat.action().action_id, action_digest=mat.action_digest)
        == mat
    )
    assert await src.current(mat) == ev

    db_state["role"] = "fdai_core"
    with pytest.raises(PermissionError, match="Executor role"):
        await src.material_for(action_id=mat.action().action_id, action_digest=mat.action_digest)
    db_state["role"] = "fdai_executor"

    db_state["source"] = "not-a-dict"
    with pytest.raises(ValueError, match="malformed evidence"):
        await src.material_for(action_id=mat.action().action_id, action_digest=mat.action_digest)

    db_state["source"] = None
    assert (
        await src.material_for(action_id=mat.action().action_id, action_digest=mat.action_digest)
        is None
    )
    with pytest.raises(ValueError, match="material source changed"):
        await src.current(mat)

    db_state["source"] = copy.deepcopy(valid_payload)
    with pytest.raises(ValueError, match="original isolated command"):
        await src.material_for(action_id=UUID(int=999), action_digest=mat.action_digest)

    for mut, match in [
        (lambda p: p.__setitem__("kill_switch", {"engaged": True}), "emergency halt"),
        (lambda p: p.__setitem__("source_count", 1001), "exceeds its bounded source"),
        (lambda p: p.__setitem__("current", None), "observation is unavailable"),
        (lambda p: p.__setitem__("case", None), "case is unavailable"),
        (lambda p: p["case"].__setitem__("revision", 99), "preparation was changed"),
        (
            lambda p: p["case"].__setitem__("extra_field", 1),
            "outside the exact source transition",
        ),
        (lambda p: p.__setitem__("promotion", None), "promotion was changed"),
        (lambda p: p.__setitem__("parks", None), "decision sources are unavailable"),
        (lambda p: p["parks"].__setitem__("approval:one", None), "decision is missing"),
        (
            lambda p: p["parks"]["approval:one"].__setitem__("submitter_oid", "other"),
            "HIL context changed",
        ),
        (
            lambda p: p["decisions"]["approval:one"].__setitem__("approver_oid", "other"),
            "HIL decision changed",
        ),
        (lambda p: p.__setitem__("database_now", None), "clock is unavailable"),
        (
            lambda p: p.__setitem__("database_now", (at + timedelta(hours=2)).isoformat()),
            "expired",
        ),
    ]:
        bad = copy.deepcopy(valid_payload)
        mut(bad)  # type: ignore[no-untyped-call]
        db_state["source"] = bad
        with pytest.raises(ValueError, match=match):
            await src.current(mat)

    # Case where case_record_digest matches original_case, but intent differs from material
    bad_intent_orig = copy.deepcopy(orig_case)
    bad_intent_orig["intent"] = "not-a-dict"
    bad_cd = human_access_record_digest(bad_intent_orig)
    bad_mat = HumanAccessExecutionMaterial.model_validate(
        {**mat.model_dump(), "case_record_digest": bad_cd}
    )
    bad_prep = HumanAccessPreparation(
        material_digest=bad_mat.digest,
        source_case_digest=bad_cd,
        source_revision=5,
        prepared_revision=6,
    )
    bad_ev = HumanAccessCurrentEvidence.model_validate(
        {
            **evidence_fn(bad_mat).model_dump(),
            "preparation_ref": bad_prep.reference,
        }
    )
    bad_intent_payload = copy.deepcopy(valid_payload)
    bad_intent_payload["material"] = bad_mat.model_dump(mode="json")
    bad_intent_payload["current"] = {"evidence": bad_ev.model_dump(mode="json")}
    bad_intent_payload["case"] = {
        **bad_intent_orig,
        "revision": 6,
        "state": "iam_applying",
        "iam_preparation": bad_prep.model_dump(mode="json"),
    }
    db_state["source"] = bad_intent_payload
    with pytest.raises(ValueError, match="intent changed"):
        await src.current(bad_mat)

    db_state["source"] = copy.deepcopy(valid_payload)
    wrong_rg_src = PostgresHumanAccessSource("postgresql://example", {"Reader": "other"})
    with pytest.raises(ValueError, match="role-group binding differs"):
        await wrong_rg_src.current(mat)

    # _require_inverse_sources branches
    with pytest.raises(ValueError, match="inverse binding is missing"):
        _require_inverse_sources({}, mat)

    intent_rec = {
        "action_digest": mat.action_digest,
        "material_digest": mat.digest,
        "target_digest": mat.membership_plan().target_digest,
        "idempotency_key": mat.action().idempotency_key,
        "before_membership": False,
        "recorded_at": at.isoformat(),
    }
    res_rec = {
        **intent_rec,
        "outcome": "succeeded",
        "receipt_ref": "human-access-dispatch:" + "1" * 64,
        "owned_mutation": True,
    }
    demand_ok = {
        "case:other": {
            "state": "revoked",
            "intent": {
                "subject": {"provider": "entra", "subject_id": mat.subject_id},
                "requested_role": mat.requested_role,
            },
        }
    }
    inv_act = mat.action().model_dump(mode="json")
    inv_act.update(
        action_id=str(UUID(int=77)),
        idempotency_key="inv:key",
        action_type="ops.revoke-human-access",
        operation="detach",
        created_at=(at + timedelta(seconds=1)).isoformat(),
        params={
            "case_id": case_id,
            "expected_revision": 5,
            "recovery_of": str(mat.action().action_id),
        },
    )
    inv_act["action_type_ref"]["name"] = "ops.revoke-human-access"
    valid_fence = {
        "state": "resolved",
        "record_digest": "sha256:" + "a" * 64,
        "identity": {
            "generation": 1,
            "sink_idempotency_key": mat.action().idempotency_key,
        },
    }
    inv_binding = HumanAccessInverseBinding(
        original_action_id=mat.action().action_id,
        original_action_digest=mat.action_digest,
        original_material_digest=mat.digest,
        original_idempotency_key=mat.action().idempotency_key,
        original_target_digest=mat.membership_plan().target_digest,
        original_attempt_digest=mutation_evidence_digest(intent_rec, res_rec),
        original_before_membership=False,
        original_receipt_ref=str(res_rec["receipt_ref"]),
        original_completed_at=at,
        target_fence_digest="sha256:" + "a" * 64,
        target_fence_generation=1,
        demand_digest=human_access_record_digest(demand_ok),
    )
    from fdai_service_contracts.executor_models import Action

    inv_mat = HumanAccessExecutionMaterial.model_validate(
        {
            **mat.model_dump(),
            "action_json": canonical_human_access_json(
                Action.model_validate(inv_act).model_dump(mode="json")
            ),
            "inverse": inv_binding,
            "recorded_at": at + timedelta(seconds=1),
            "expires_at": at + timedelta(minutes=5),
        }
    )
    with pytest.raises(ValueError, match="inverse original evidence changed"):
        _require_inverse_sources({"inverse_original": mat.model_dump(mode="json")}, inv_mat)

    inv_payload: dict[str, object] = {
        "inverse_original": mat.model_dump(mode="json"),
        "inverse_intent": intent_rec,
        "inverse_result": res_rec,
        "target_fence": valid_fence,
        "recovery_demand": demand_ok,
    }
    _require_inverse_sources(inv_payload, inv_mat)

    with pytest.raises(ValueError, match="membership demand changed"):
        _require_inverse_sources({**inv_payload, "recovery_demand": {}}, inv_mat)

    for bad_demand, match in [
        ({"c1": "not-a-dict"}, "inverse demand is malformed"),
        (
            {
                "c1": {
                    "state": "active",
                    "intent": {
                        "subject": {"provider": "entra", "subject_id": mat.subject_id},
                        "requested_role": mat.requested_role,
                    },
                }
            },
            "required by another assignment",
        ),
    ]:
        bad_inv_mat = inv_mat.model_copy(
            update={
                "inverse": inv_binding.model_copy(
                    update={"demand_digest": human_access_record_digest(bad_demand)}
                )
            }
        )
        with pytest.raises(ValueError, match=match):
            _require_inverse_sources({**inv_payload, "recovery_demand": bad_demand}, bad_inv_mat)
