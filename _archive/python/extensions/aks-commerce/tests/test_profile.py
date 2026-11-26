from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml
from fdai.agents import AnomalyActionCandidate
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.shared.contracts.models import (
    CeilingRole,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    SafeguardBoundExecutorCommand,
    Severity,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _rule

from fdai_aks_commerce import (
    load_resource_manifest,
    load_resources,
    load_scenario_profile,
    load_slo_documents,
)
from fdai_aks_commerce.acceptance import OrderAcceptanceAnalyzer, OrderAcceptanceIntent
from fdai_aks_commerce.acceptance_action import ACCEPTANCE_SIGNAL, AcceptanceAnomalyActionSource
from fdai_aks_commerce.acceptance_authority import AcceptanceCurrentAuthority
from fdai_aks_commerce.acceptance_material import (
    AcceptanceDispatchMaterial,
    StoredAcceptanceDispatchMaterials,
)
from fdai_aks_commerce.acceptance_preparation import PreparedAcceptanceSource
from fdai_aks_commerce.cli import main as cli_main
from fdai_aks_commerce.profile import (
    AksCommerceProfileError,
    AksCommerceResource,
    load_resource_bytes,
)
from fdai_aks_commerce.synthetic import StorefrontJourneyResult

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_manifest_is_inert_canonical_and_complete() -> None:
    manifest = load_resource_manifest()
    resources = load_resources()

    assert manifest["candidate_state"] == "inert"
    assert [resource.resource_id for resource in resources] == sorted(
        resource.resource_id for resource in resources
    )
    assert {resource.kind for resource in resources} == {"profile", "slo", "workflow"}


def test_profile_declares_reviewed_business_dependency_paths() -> None:
    profile = load_scenario_profile()

    assert {service["id"] for service in profile["services"]} == {
        "catalog-browse",
        "order-fulfillment",
    }
    assert {(link["from_id"], link["link_type"], link["to_id"]) for link in profile["links"]} >= {
        ("storefront", "workload_depends_on", "order-api"),
        ("order-api", "workload_depends_on", "order-queue"),
        ("order-queue", "workload_depends_on", "order-processor"),
        ("order-processor", "workload_depends_on", "order-store"),
    }


def test_packaged_slos_pass_shared_schema() -> None:
    slos = load_slo_documents()

    assert {slo["id"] for slo in slos} == {
        "catalog-browse.availability",
        "order-fulfillment.availability",
        "order-fulfillment.freshness",
    }


def test_profile_resource_loader_rejects_invalid_paths_and_manifests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for invalid_path in ("", "../manifest.json", "./manifest.json", "slos//a.yaml"):
        with pytest.raises(AksCommerceProfileError, match="package-relative"):
            load_resource_bytes(invalid_path)
    with pytest.raises(AksCommerceProfileError, match="does not exist"):
        load_resource_bytes("missing-resource.json")

    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resource_bytes",
        lambda _path: b"{not-json",
    )
    with pytest.raises(AksCommerceProfileError, match="valid UTF-8 JSON"):
        load_resource_manifest()

    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resource_bytes",
        lambda _path: b'{"schema_version":"0.0.0"}',
    )
    with pytest.raises(AksCommerceProfileError, match="manifest shape is invalid"):
        load_resource_manifest()


@pytest.mark.parametrize(
    ("resources_list", "match"),
    [
        ([{"id": "only-id"}], "resource declaration is invalid"),
        (
            [
                {"id": "dup", "kind": "profile", "path": "a.json", "sha256": "0" * 64},
                {"id": "dup", "kind": "profile", "path": "b.json", "sha256": "0" * 64},
            ],
            "unique",
        ),
        (
            [{"id": "a", "kind": "unknown", "path": "scenario-profile.json", "sha256": "0" * 64}],
            "kind is unsupported",
        ),
        (
            [{"id": "a", "kind": "profile", "path": "scenario-profile.json", "sha256": "0" * 64}],
            "digest mismatch",
        ),
    ],
)
def test_load_resources_rejects_invalid_declarations(
    monkeypatch: pytest.MonkeyPatch,
    resources_list: list[dict[str, str]],
    match: str,
) -> None:
    content = b"{}"
    digest = hashlib.sha256(content).hexdigest()
    normalized = [
        {**item, "sha256": digest if match == "unique" else item.get("sha256", "")}
        if "sha256" in item
        else item
        for item in resources_list
    ]
    monkeypatch.setattr("fdai_aks_commerce.profile.load_resource_bytes", lambda _path: content)
    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resource_manifest",
        lambda: {"resources": normalized},
    )
    with pytest.raises(AksCommerceProfileError, match=match):
        load_resources()


def test_load_resources_requires_canonical_id_order(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"{}"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resource_manifest",
        lambda: {
            "resources": [
                {"id": "b", "kind": "profile", "path": "b.json", "sha256": digest},
                {"id": "a", "kind": "profile", "path": "a.json", "sha256": digest},
            ]
        },
    )
    monkeypatch.setattr("fdai_aks_commerce.profile.load_resource_bytes", lambda _path: content)
    with pytest.raises(AksCommerceProfileError, match="canonical id order"):
        load_resources()


def test_load_slo_and_profile_reject_invalid_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resources",
        lambda: (AksCommerceResource("s1", "slo", "slos/bad.yaml", "0" * 64, b"- list-item\n"),),
    )
    with pytest.raises(AksCommerceProfileError, match="YAML object"):
        load_slo_documents()

    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resources",
        lambda: (AksCommerceResource("s1", "slo", "slos/bad.yaml", "0" * 64, b"id: invalid\n"),),
    )
    with pytest.raises(AksCommerceProfileError, match="slos/bad.yaml"):
        load_slo_documents()

    monkeypatch.setattr("fdai_aks_commerce.profile.load_resources", lambda: ())
    with pytest.raises(AksCommerceProfileError, match="exactly one profile"):
        load_scenario_profile()

    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resources",
        lambda: (AksCommerceResource("p1", "profile", "p.json", "0" * 64, b"{invalid"),),
    )
    with pytest.raises(AksCommerceProfileError, match="valid UTF-8 JSON"):
        load_scenario_profile()

    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resources",
        lambda: (AksCommerceResource("p1", "profile", "p.json", "0" * 64, b"[]"),),
    )
    with pytest.raises(AksCommerceProfileError, match="JSON object"):
        load_scenario_profile()


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda d: d.pop("slos"), "profile shape is invalid"),
        (lambda d: d.__setitem__("services", "not-a-list"), "collections must be arrays"),
        (lambda d: d.__setitem__("services", [{"id": 123}]), "service declaration is invalid"),
        (
            lambda d: d.__setitem__(
                "services", [{"id": "catalog-browse"}, {"id": "catalog-browse"}]
            ),
            "service ids must be unique",
        ),
        (
            lambda d: d.__setitem__("services", [{"id": "catalog-browse"}]),
            "service ids are invalid",
        ),
        (lambda d: d.__setitem__("links", [{"from_id": "a"}]), "profile link is invalid"),
        (
            lambda d: d.__setitem__(
                "links", [{"from_id": "catalog-browse", "link_type": "unknown", "to_id": "x"}]
            ),
            "link target is invalid",
        ),
    ],
)
def test_validate_profile_rejects_invalid_topology(
    monkeypatch: pytest.MonkeyPatch,
    mutator: Any,
    match: str,
) -> None:
    valid = load_scenario_profile()
    mutator(valid)
    raw = json.dumps(valid).encode("utf-8")
    monkeypatch.setattr(
        "fdai_aks_commerce.profile.load_resources",
        lambda: (AksCommerceResource("p1", "profile", "p.json", "0" * 64, raw),),
    )
    with pytest.raises(AksCommerceProfileError, match=match):
        load_scenario_profile()


def _valid_cli_frame_dict(service_id: str = "catalog-browse") -> dict[str, Any]:
    return {
        "service_id": service_id,
        "observed_at": NOW.isoformat(),
        "window_start": (NOW - timedelta(minutes=5)).isoformat(),
        "window_end": NOW.isoformat(),
        "dependency_path": ["storefront"],
        "workloads": [
            {
                "workload_id": "storefront",
                "display_name": "Storefront",
                "resource_ref": "resource:storefront",
                "ready": True,
                "evidence_state": "complete",
            }
        ],
        "slos": [
            {
                "slo_id": "catalog-browse.availability",
                "objective_ratio": 0.99,
                "observed_ratio": 1.0,
                "budget_remaining_ratio": 1.0,
                "breached": False,
                "state": "complete",
                "source_ref": "source:slo",
            }
        ],
        "metrics": [
            {
                "name": "synthetic.catalog.availability",
                "unit": "ratio",
                "current": 1.0,
                "previous": 1.0,
                "source_ref": "source:metric",
                "observed_at": NOW.isoformat(),
                "state": "complete",
            }
        ],
        "evidence_refs": ["evidence:1"],
    }


def test_cli_assess_and_persist_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "frame.json"
    payload = _valid_cli_frame_dict("catalog-browse")
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cli_main(["assess", "--input", str(input_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["service_id"] == "catalog-browse"

    order_payload = {
        **_valid_cli_frame_dict("order-fulfillment"),
        "evidence_gaps": ["explicit_gap"],
        "synthetic": True,
    }
    input_path.write_text(json.dumps(order_payload), encoding="utf-8")

    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    with pytest.raises(RuntimeError, match="FDAI_STATE_STORE_DSN is required"):
        cli_main(["assess", "--input", str(input_path), "--persist"])

    writes: list[tuple[str, Any]] = []

    class _FakePostgresStore:
        def __init__(self, *, config: Any) -> None:
            self.dsn = config.dsn

        async def write_state(self, key: str, value: Any) -> None:
            writes.append((key, value))

    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost:5432/fdai")
    monkeypatch.setattr("fdai_aks_commerce.cli.PostgresStateStore", _FakePostgresStore)
    assert cli_main(["assess", "--input", str(input_path), "--persist"]) == 0
    assert len(writes) == 2
    assert writes[1][0].endswith(":latest")


def test_cli_journey_and_input_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for success, expected_code in ((True, 0), (False, 2)):

        async def _fake_run(
            _self: Any, config: Any, *, ok: bool = success
        ) -> StorefrontJourneyResult:
            return StorefrontJourneyResult(
                observed_at=NOW,
                success=ok,
                failed_step=None if ok else "browse",
                duration_ms=12,
                evidence_ref="synthetic-journey:sha256:" + "a" * 64,
                authorization_ref=config.authorization_ref,
                order_http_status=201 if ok else None,
            )

        monkeypatch.setattr(
            "fdai_aks_commerce.cli.AsyncPlaywrightStorefrontDriver.run",
            _fake_run,
        )
        rc = cli_main(
            [
                "journey",
                "--url",
                "https://store.example.com",
                "--authorization-ref",
                "auth:1",
                "--authorization-expires-at",
                "2026-09-17T13:00:00Z",
            ]
        )
        assert rc == expected_code

    for bad_expiry, match in (
        ("not-iso", "ISO 8601 timestamp"),
        ("2026-09-17T13:00:00", "include a timezone"),
    ):
        with pytest.raises(ValueError, match=match):
            cli_main(
                [
                    "journey",
                    "--url",
                    "https://store.example.com",
                    "--authorization-ref",
                    "auth:1",
                    "--authorization-expires-at",
                    bad_expiry,
                ]
            )

    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="readable UTF-8 JSON"):
        cli_main(["assess", "--input", str(bad_file)])

    bad_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        cli_main(["assess", "--input", str(bad_file)])

    bad_file.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or unknown"):
        cli_main(["assess", "--input", str(bad_file)])

    cases: list[tuple[dict[str, Any], str]] = [
        ({"service_id": ""}, "service_id must be non-empty text"),
        ({"service_id": "unknown-service"}, "service_id is unsupported"),
        ({"observed_at": "bad"}, "observed_at must be an ISO 8601"),
        ({"observed_at": "2026-09-17T12:00:00"}, "observed_at must include a timezone"),
        ({"dependency_path": "not-a-list"}, "dependency_path must be an array of strings"),
        ({"workloads": ["not-an-object"]}, "workloads must be an array of objects"),
        ({"synthetic": "not-a-bool"}, "synthetic must be a boolean"),
    ]
    for override, match in cases:
        doc = {**_valid_cli_frame_dict(), **override}
        bad_file.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            cli_main(["assess", "--input", str(bad_file)])


async def test_acceptance_material_authority_and_preparation_edges() -> None:
    intent = OrderAcceptanceIntent(
        policy_ref="policy:example",
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )
    rule = _rule().model_copy(
        update={
            "remediates": "ops.scale-out",
            "resource_type": "kubernetes.deployment",
            "check_logic": _rule().check_logic.model_copy(
                update={"reference": "fdai.aks_commerce.order_acceptance.v1"}
            ),
        }
    )
    action = _direct_action(
        action_id="00000000-0000-0000-0000-000000000010",
        target=intent.resource_ref,
        mode=Mode.ENFORCE,
        citing_rules=(rule.id,),
        params={"target_resource_ref": intent.resource_ref, "replica_count": 1},
    ).model_copy(update={"action_type": "ops.scale-out", "operation": Operation.SCALE})
    valid_json = action.model_dump_json()

    with pytest.raises(ValueError, match="bounded distinct observation references"):
        AcceptanceDispatchMaterial(valid_json, "corr", "key", evidence_refs=("",))
    with pytest.raises(ValueError, match="canonical Rule digest"):
        AcceptanceDispatchMaterial(valid_json, "corr", "key", rule_digest="bad")
    with pytest.raises(ValueError, match="exact bounded lineage"):
        AcceptanceDispatchMaterial(valid_json, " ", "key")
    with pytest.raises(ValueError, match="Action exceeds its bound"):
        AcceptanceDispatchMaterial("x" * 70_000, "corr", "key")
    other_action = action.model_copy(update={"action_type": "ops.restart"})
    with pytest.raises(ValueError, match="canonical registered scale Action"):
        AcceptanceDispatchMaterial(other_action.model_dump_json(), "corr", "key")

    store = InMemoryStateStore()
    materials = StoredAcceptanceDispatchMaterials(store)
    mat = AcceptanceDispatchMaterial(valid_json, "corr", "key")
    await materials.retain(mat)
    with pytest.raises(ValueError, match="already binds different content"):
        await materials.retain(AcceptanceDispatchMaterial(valid_json, "corr-other", "key"))
    with pytest.raises(ValueError, match="Action id must be canonical"):
        await materials.read(UUID(int=1).hex)

    key_str = "aks-commerce:acceptance-action:v1:" + str(action.action_id)
    await store.write_state(key_str, {"schema_version": "0.0.0"})
    with pytest.raises(ValueError, match="material is malformed"):
        await materials.read(str(action.action_id))
    await store.write_state(
        key_str,
        {
            "schema_version": "1.0.0",
            "material": {
                "action_json": valid_json,
                "correlation_id": "corr",
                "action_run_idempotency_key": "key",
                "rule_digest": None,
                "evidence_refs": "not-a-list",
            },
            "digest": "sha256:" + "0" * 64,
        },
    )
    with pytest.raises(ValueError, match="must be a JSON array"):
        await materials.read(str(action.action_id))
    await store.write_state(
        key_str,
        {
            "schema_version": "1.0.0",
            "material": {
                "action_json": valid_json,
                "correlation_id": "corr",
                "action_run_idempotency_key": "key",
                "rule_digest": None,
            },
            "digest": "sha256:" + "0" * 64,
        },
    )
    with pytest.raises(ValueError, match="integrity mismatch"):
        await materials.read(str(action.action_id))

    with pytest.raises(ValueError, match="command id must be canonical"):
        await materials.link_command(action, UUID(int=1).hex)
    store2 = InMemoryStateStore()
    materials2 = StoredAcceptanceDispatchMaterials(store2)
    with pytest.raises(ValueError, match="command readback is unavailable"):
        await materials2.link_command(action, str(UUID(int=100)))
    await materials2.retain(mat)
    cmd = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=101),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=NOW,
        deadline_at=NOW + timedelta(seconds=30),
        safeguard_proof_bundle_digest="sha256:" + "b" * 64,
        source_revision="rev-1",
    )
    corr = BoundCommandCorrelation(
        command=cmd,
        registration_id=UUID(int=102),
        reservation_identity_digest="sha256:" + "c" * 64,
        evidence_identity_digest="sha256:" + "d" * 64,
        target_digest="sha256:" + "e" * 64,
        target_fence_generation=1,
    )
    await store2.write_state(
        "runtime:isolated-executor:command:" + str(UUID(int=100)),
        corr.model_dump(mode="json"),
    )
    with pytest.raises(ValueError, match="changed the original Action"):
        await materials2.link_command(action, str(UUID(int=100)))

    await store2.write_state(
        "runtime:isolated-executor:command:" + str(UUID(int=101)),
        corr.model_dump(mode="json"),
    )
    await store2.write_state(
        "aks-commerce:acceptance-command:v1:" + str(action.action_id),
        {"command_id": "other", "closure_key": "other"},
    )
    with pytest.raises(ValueError, match="already has a different command"):
        await materials2.link_command(action, str(UUID(int=101)))

    action_type = OntologyActionType.model_validate(
        yaml.safe_load(
            (
                Path(__file__).resolve().parents[3] / "rule-catalog/action-types/ops.scale-out.yaml"
            ).read_text()
        )
    )
    builder = ActionBuilder({action_type.name: action_type})
    risk_gate = RiskGate(registry=ActionPromotionRegistry())
    authority = AcceptanceCurrentAuthority(
        store=store2,
        builder=builder,
        rule=rule,
        risk_gate=risk_gate,
        risk_table=load_risk_table(
            Path(__file__).resolve().parents[3] / "rule-catalog/risk-classification.yaml"
        ),
        principal_role=CeilingRole.APPROVER,
        can_approve=lambda _p, _a: True,
        refresh_policy=lambda: _noop_async(),
        safety_held=lambda: False,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="reviewed scale recovery Rule"):
        await authority(other_action, {})
    with pytest.raises(ValueError, match="Rule material is unavailable"):
        await authority(action, {})

    rule_digest = "sha256:" + hashlib.sha256(rule.model_dump_json().encode()).hexdigest()
    bad_citing = action.model_copy(
        update={
            "action_id": UUID(int=202),
            "citing_rules": ["other-rule"],
        }
    )
    await materials2.retain(
        AcceptanceDispatchMaterial(bad_citing.model_dump_json(), "corr", "key", rule_digest)
    )
    with pytest.raises(ValueError, match="action catalog or Rule changed"):
        await authority(bad_citing, {})

    dummy_source = AcceptanceAnomalyActionSource(
        intent=intent,
        analyzer=OrderAcceptanceAnalyzer(
            intent=intent,
            source=SimpleNamespace(observe=lambda _i: _noop_async()),  # type: ignore[arg-type]
            verifier=SimpleNamespace(verify=lambda **_kw: _noop_async()),  # type: ignore[arg-type]
            resource_kind="kubernetes.deployment",
            severity=Severity.HIGH,
            clock=lambda: NOW,
        ),
    )
    with pytest.raises(ValueError, match="reviewed scale recovery Rule"):
        PreparedAcceptanceSource(
            source=dummy_source,
            builder=builder,
            rule=_rule(),
            risk_gate=risk_gate,
            materials=materials2,
            refresh_policy=lambda: _noop_async(),
        )
    prepared = PreparedAcceptanceSource(
        source=dummy_source,
        builder=builder,
        rule=rule,
        risk_gate=risk_gate,
        materials=materials2,
        refresh_policy=lambda: _noop_async(),
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="judge-owned human-review decision"):
        await prepared.prepare({"producer_principal": "Other"})

    cand_args = {
        "target_resource_ref": intent.resource_ref,
        "target_platform": "kubernetes",
        "target_kind": "Deployment",
        "cluster_ref": intent.cluster_ref,
        "namespace": intent.namespace,
        "resource_name": intent.deployment_name,
        "target_uid": intent.deployment_uid,
        "resource_version": "1",
        "replica_count": 1,
        "reason": "Restore the reviewed order-acceptance replica floor.",
    }
    cand = AnomalyActionCandidate(
        event_type=ACCEPTANCE_SIGNAL,
        resource_ref=intent.resource_ref,
        action_type="ops.scale-out",
        arguments_json=json.dumps(cand_args, sort_keys=True, separators=(",", ":")),
        evidence_ref="sha256:" + "d" * 64,
        observed_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    verdict = {
        "producer_principal": "Forseti",
        "initiator_principal": "Heimdall",
        "risk_verdict": "hil",
        "resource_id": intent.resource_ref,
        "anomaly_action_evidence": {"evidence_ref": cand.evidence_ref},
        "action_type": "ops.scale-out",
        "params": cand_args,
        "correlation_id": "corr-prep",
        "idempotency_key": "key-prep",
        "resolved_autonomy_ceiling": "enforce_hil",
    }

    class _PrepSource:
        def __init__(self, digest: str) -> None:
            self.digest = digest

        async def resolve(self, **_kw: Any) -> AnomalyActionCandidate:
            return cand

        async def assess(self) -> Any:
            return SimpleNamespace(evidence_digest=self.digest, evidence_refs=("ref:1",))

    no_trigger_builder = ActionBuilder(
        {action_type.name: action_type.model_copy(update={"trigger_kind": None})}
    )
    with pytest.raises(ValueError, match="automatic rule findings"):
        await PreparedAcceptanceSource(
            source=_PrepSource(cand.evidence_ref),  # type: ignore[arg-type]
            builder=no_trigger_builder,
            rule=rule,
            risk_gate=risk_gate,
            materials=materials2,
            refresh_policy=lambda: _noop_async(),
            clock=lambda: NOW,
        ).prepare(verdict)

    no_schema_builder = ActionBuilder(
        {action_type.name: action_type.model_copy(update={"argument_schema": None})}
    )
    with pytest.raises(ValueError, match="argument schema is unavailable"):
        await PreparedAcceptanceSource(
            source=_PrepSource(cand.evidence_ref),  # type: ignore[arg-type]
            builder=no_schema_builder,
            rule=rule,
            risk_gate=risk_gate,
            materials=materials2,
            refresh_policy=lambda: _noop_async(),
            clock=lambda: NOW,
        ).prepare(verdict)

    denied_gate = SimpleNamespace(
        evaluate=lambda **_kw: SimpleNamespace(
            outcome=SimpleNamespace(value="denied"), effective_mode=Mode.SHADOW
        )
    )
    with pytest.raises(ValueError, match="not admitted by the current risk policy"):
        await PreparedAcceptanceSource(
            source=_PrepSource(cand.evidence_ref),  # type: ignore[arg-type]
            builder=builder,
            rule=rule,
            risk_gate=denied_gate,  # type: ignore[arg-type]
            materials=materials2,
            refresh_policy=lambda: _noop_async(),
            clock=lambda: NOW,
        ).prepare(verdict)

    with pytest.raises(ValueError, match="changed before original material retention"):
        await PreparedAcceptanceSource(
            source=_PrepSource("sha256:" + "0" * 64),  # type: ignore[arg-type]
            builder=builder,
            rule=rule,
            risk_gate=risk_gate,
            materials=materials2,
            refresh_policy=lambda: _noop_async(),
            clock=lambda: NOW,
        ).prepare(verdict)

    ticks = iter([NOW, NOW, NOW, NOW + timedelta(seconds=31)])
    with pytest.raises(ValueError, match="expired during original Action retention"):
        await PreparedAcceptanceSource(
            source=_PrepSource(cand.evidence_ref),  # type: ignore[arg-type]
            builder=builder,
            rule=rule,
            risk_gate=risk_gate,
            materials=StoredAcceptanceDispatchMaterials(InMemoryStateStore()),
            refresh_policy=lambda: _noop_async(),
            clock=lambda: next(ticks),
        ).prepare(verdict)

    conflict_store = InMemoryStateStore()
    conflict_mats = StoredAcceptanceDispatchMaterials(conflict_store)
    prep_ok = PreparedAcceptanceSource(
        source=_PrepSource(cand.evidence_ref),  # type: ignore[arg-type]
        builder=builder,
        rule=rule,
        risk_gate=risk_gate,
        materials=conflict_mats,
        refresh_policy=lambda: _noop_async(),
        clock=lambda: NOW,
    )
    res_prep = await prep_ok.prepare(verdict)
    existing_mat = await conflict_mats.read(res_prep.action_id)
    assert existing_mat is not None
    await conflict_store.write_state(
        "aks-commerce:acceptance-action:v1:" + res_prep.action_id,
        {
            "schema_version": "1.0.0",
            "material": {
                "action_json": existing_mat.action_json,
                "correlation_id": "corr-prep",
                "action_run_idempotency_key": "key-prep",
                "rule_digest": "sha256:" + "f" * 64,
                "evidence_refs": ["ref:1"],
            },
            "digest": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "action_json": existing_mat.action_json,
                        "correlation_id": "corr-prep",
                        "action_run_idempotency_key": "key-prep",
                        "rule_digest": "sha256:" + "f" * 64,
                        "evidence_refs": ["ref:1"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
    )
    with pytest.raises(ValueError, match="original Action changed"):
        await prep_ok.prepare(verdict)


async def _noop_async() -> None:
    return None
