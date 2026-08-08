"""Unified P1 control-loop coverage across all three verticals.

Proves the phase-3 § Unified Control Loop invariant *for the P1 slice*:
a single :class:`ControlLoop` instance routes Change Safety, Resilience,
and Cost Governance events end-to-end without vertical-specific
branching. P1 does not wire the risk-gate / T1 / T2 into the loop, so
the assertion is scoped to what P1 actually delivers:

- **Same loop instance handles all three verticals.** One
  :class:`ControlLoop` with the shipped catalog processes events from
  every domain; each domain reaches ``EXECUTED`` on a matching rule.
- **Shadow-mode invariant** holds cross-vertical - every published PR
  carries the ``shadow`` label, every executed action reports
  :class:`Mode.SHADOW`.
- **Vertical isolation** - an event routed by resource_type never fires
  a rule from a different vertical (Change rule never fires on FinOps
  event, etc.). This proves resource_type routing is the right isolation
  boundary; verticals do not need per-loop instances.
- **Idempotency across verticals** - replaying a burst of mixed-domain
  events under the same idempotency keys deduplicates deterministically.

The full P3 unified loop (risk-gate precedence, cross-vertical lock,
per-vertical Managed Identity) is beyond the P1 loop's contract; that
gets tested in P3 once the risk-gate is wired.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from fdai.core.control_loop import (
    ControlLoop,
    ControlLoopOutcome,
    ControlLoopResult,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAccessGrantProposal,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from tests.verified_shadow_executor import VerifiedShadowExecutor

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT,
    reason="opa binary not found on PATH; skip unified-loop e2e",
)


@pytest.fixture(scope="module")
def shipped_catalog() -> tuple[Any, Any]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    return rules, action_types


def _make_loop(
    shipped_catalog: tuple[Any, Any],
    *,
    execution_authorization_evaluator: Any = None,
) -> tuple[ControlLoop, RecordingRemediationPrPublisher, InMemoryStateStore]:
    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = VerifiedShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    action_builder = ActionBuilder(action_types_by_name={a.name: a for a in action_types})
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=evaluator),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
        execution_authorization_evaluator=execution_authorization_evaluator,
    )
    return loop, publisher, audit


class _AuthorizationEvaluator:
    def __init__(self, status: ExecutionAuthorizationStatus) -> None:
        self.status = status
        self.requests: list[ExecutionAuthorizationRequest] = []

    async def evaluate(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorizationResult:
        self.requests.append(request)
        proposal = None
        if self.status is ExecutionAuthorizationStatus.GRANT_REQUIRED:
            now = datetime(2026, 7, 31, tzinfo=UTC)
            proposal = ExecutionAccessGrantProposal(
                idempotency_key=request.idempotency_key,
                original_action_id=request.action_id,
                authorization_decision_digest="decision-grant_required",
                requirement_id="requirement.object-write",
                capability_id="object.write",
                execution_profile="change-executor",
                executor_identity_ref="identity/change",
                scope_ref="scope://example/account/prod/store-1",
                grant_mode="time_bound",
                mapping_digest="mapping-v1",
                plan_digest="plan-v1",
                requester_ref="requester-1",
                requested_at=now,
                expires_at=now + timedelta(minutes=30),
                quorum=1,
                approver_roles=frozenset({"owner"}),
            )
        return ExecutionAuthorizationResult(
            status=self.status,
            decision_digest=f"decision-{self.status.value}",
            evaluator_ref="test.authorization-evaluator",
            reason_codes=(f"test_{self.status.value}",),
            executor_identity_ref=(
                "identity/change"
                if self.status is ExecutionAuthorizationStatus.AUTHORIZED
                else None
            ),
            grant_proposals=(proposal,) if proposal is not None else (),
        )


class _RaisingAuthorizationEvaluator:
    async def evaluate(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorizationResult:
        del request
        raise RuntimeError("authorization source unavailable")


def test_authorization_result_rejects_sensitive_or_mutable_audit_context() -> None:
    with pytest.raises(ValueError, match="identify one executor identity"):
        ExecutionAuthorizationResult(
            status=ExecutionAuthorizationStatus.AUTHORIZED,
            decision_digest="decision-authorized",
            evaluator_ref="test-evaluator",
            reason_codes=("authorized",),
        )
    with pytest.raises(ValueError, match="sensitive key"):
        ExecutionAuthorizationResult(
            status=ExecutionAuthorizationStatus.PROHIBITED,
            decision_digest="decision-1",
            evaluator_ref="test-evaluator",
            reason_codes=("denied",),
            audit_context={"access_token": "secret"},
        )
    context: dict[str, object] = {"policy_version": "1"}
    result = ExecutionAuthorizationResult(
        status=ExecutionAuthorizationStatus.PROHIBITED,
        decision_digest="decision-1",
        evaluator_ref="test-evaluator",
        reason_codes=("denied",),
        audit_context=context,
    )
    context["policy_version"] = "2"
    assert result.audit_context["policy_version"] == "1"


class _GrantSink:
    def __init__(self) -> None:
        self.proposals: list[ExecutionAccessGrantProposal] = []

    async def submit_grant(self, proposal: ExecutionAccessGrantProposal) -> str:
        self.proposals.append(proposal)
        return "grant-request-1"


def _event(
    *,
    idempotency_key: str,
    resource_type: str,
    resource_id: str,
    props: dict[str, Any],
    event_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "source": "example_activity_log",
        "event_type": "config_changed",
        "detected_at": "2026-07-06T08:00:00Z",
        "ingested_at": "2026-07-06T08:00:01Z",
        "mode": "shadow",
        "payload": {
            "resource": {
                "resource_id": resource_id,
                "type": resource_type,
                "props": props,
            }
        },
    }


# ---------------------------------------------------------------------------
# Per-vertical trigger events - each fires a shipped rule of its family
# ---------------------------------------------------------------------------

_VERTICAL_TRIGGERS: dict[str, dict[str, Any]] = {
    "change": {
        "idempotency_key": "unified-change-1",
        "resource_type": "object-storage",
        "resource_id": "stg-open",
        "props": {"public_access": "enabled", "tags": {"owner": "team-a"}},
        "event_id": "00000000-0000-0000-0000-000000000201",
        "expected_rule_family": "object-storage.public-access.deny",
    },
    "resilience": {
        "idempotency_key": "unified-resilience-1",
        "resource_type": "sql-database",
        "resource_id": "sqldb-1",
        "props": {
            "tde_enabled": False,
        },
        "event_id": "00000000-0000-0000-0000-000000000202",
        "expected_rule_family": "sql-database.tde-required",
    },
    "finops": {
        "idempotency_key": "unified-finops-1",
        "resource_type": "network.public-ip",
        "resource_id": "pip-orphan-1",
        "props": {"associated_resource_id": ""},
        "event_id": "00000000-0000-0000-0000-000000000203",
        "expected_rule_family": "network.public-ip.orphan",
    },
}


@requires_opa
async def test_prohibited_authorization_never_reaches_executor(
    shipped_catalog: tuple[Any, Any],
) -> None:
    evaluator = _AuthorizationEvaluator(ExecutionAuthorizationStatus.PROHIBITED)
    loop, publisher, audit = _make_loop(
        shipped_catalog,
        execution_authorization_evaluator=evaluator,
    )
    spec = dict(_VERTICAL_TRIGGERS["change"])
    spec.pop("expected_rule_family")

    result = await loop.process(_event(**spec))

    assert result.outcome is ControlLoopOutcome.DENIED
    assert not publisher.records
    assert evaluator.requests
    assert any(
        record["entry"].get("action_kind") == "execution_authorization.decided"
        and record["entry"].get("decision") == "prohibited"
        for record in audit.audit_entries
    )


@requires_opa
async def test_authorization_evaluator_failure_holds_without_execution(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(
        shipped_catalog,
        execution_authorization_evaluator=_RaisingAuthorizationEvaluator(),
    )
    spec = dict(_VERTICAL_TRIGGERS["change"])
    spec.pop("expected_rule_family")

    result = await loop.process(_event(**spec))

    assert result.outcome is ControlLoopOutcome.HIL
    assert not publisher.records
    assert any(
        record["entry"].get("action_kind") == "execution_authorization.decided"
        and record["entry"].get("decision") == "unknown"
        and record["entry"].get("reason_codes") == ["evaluator_unavailable"]
        for record in audit.audit_entries
    )


@requires_opa
async def test_grant_required_submits_separate_request_without_execution(
    shipped_catalog: tuple[Any, Any],
) -> None:
    evaluator = _AuthorizationEvaluator(ExecutionAuthorizationStatus.GRANT_REQUIRED)
    sink = _GrantSink()
    rules, action_types = shipped_catalog
    loop, publisher, audit = _make_loop(
        (rules, action_types),
        execution_authorization_evaluator=evaluator,
    )
    loop._execution_access_grant_sink = sink
    spec = dict(_VERTICAL_TRIGGERS["change"])
    spec.pop("expected_rule_family")

    result = await loop.process(_event(**spec))

    assert result.outcome is ControlLoopOutcome.HIL
    assert not publisher.records
    assert sink.proposals
    assert any(
        record["entry"].get("grant_requests")
        == [
            {
                "requirement_id": "requirement.object-write",
                "scope_ref": "scope://example/account/prod/store-1",
                "request_id": "grant-request-1",
                "state": "submitted",
            }
        ]
        and record["entry"].get("actor") == "test.authorization-evaluator"
        and record["entry"].get("grant_execution_profiles") == ["change-executor"]
        for record in audit.audit_entries
    )


@requires_opa
@pytest.mark.asyncio
async def test_single_loop_handles_all_three_verticals(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """One :class:`ControlLoop` instance routes all three verticals.

    Proves the shape of the P3 unified-loop contract at the P1 level:
    the loop is domain-agnostic; verticals are configuration, not code
    branches inside the loop.
    """
    loop, publisher, audit = _make_loop(shipped_catalog)
    domain_outcomes: dict[str, ControlLoopResult] = {}

    for domain, spec in _VERTICAL_TRIGGERS.items():
        payload = dict(spec)
        payload.pop("expected_rule_family", None)
        result = await loop.process(_event(**payload))
        domain_outcomes[domain] = result

    for domain, result in domain_outcomes.items():
        expected_rule = _VERTICAL_TRIGGERS[domain]["expected_rule_family"]
        assert result.outcome is ControlLoopOutcome.EXECUTED, (
            f"{domain} vertical: expected EXECUTED, got {result.outcome} (reason={result.reason})"
        )
        assert result.tier == "t0"
        assert result.decision == "auto"
        assert expected_rule in result.citing_rule_ids, (
            f"{domain} vertical: expected shipped rule {expected_rule!r} "
            f"in citing_rule_ids={result.citing_rule_ids}"
        )
        # Shadow-mode invariant per execution.
        for execution in result.execution_results:
            assert execution.mode is Mode.SHADOW

    # Shadow-mode invariant on the publisher - every PR carries the
    # shadow label, no vertical is bypassing it.
    assert publisher.records, "no PRs published for any vertical"
    for pr in publisher.records:
        assert pr.mode is Mode.SHADOW
        assert "shadow" in pr.labels

    # Every vertical wrote at least one audit entry.
    audit_entries = list(audit.audit_entries)
    assert len(audit_entries) >= len(_VERTICAL_TRIGGERS)


@requires_opa
@pytest.mark.asyncio
async def test_vertical_isolation_no_cross_family_matches(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """A vertical's event MUST cite only rules that target its resource_type.

    Guarantees resource_type is the correct isolation boundary: a Change
    Safety event never accidentally fires a FinOps rule, and so on.
    """
    loop, _publisher, _audit = _make_loop(shipped_catalog)
    rules, _action_types = shipped_catalog
    rules_by_id = {r.id: r for r in rules}

    for domain, spec in _VERTICAL_TRIGGERS.items():
        payload = dict(spec)
        payload.pop("expected_rule_family", None)
        # Give each event a unique idempotency_key so the loop doesn't
        # dedupe against the previous test's audit.
        payload["idempotency_key"] = f"isolation-{domain}"
        result = await loop.process(_event(**payload))
        assert result.outcome is ControlLoopOutcome.EXECUTED

        expected_type = spec["resource_type"]
        for cited_id in result.citing_rule_ids:
            cited_rule = rules_by_id[cited_id]
            assert cited_rule.resource_type == expected_type, (
                f"{domain} vertical fired {cited_id!r} whose resource_type "
                f"{cited_rule.resource_type!r} != event resource_type "
                f"{expected_type!r} - cross-vertical leak"
            )


@requires_opa
@pytest.mark.asyncio
async def test_idempotent_replay_across_verticals(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Re-delivering the same event batch produces zero new PRs.

    A single instance of the loop MUST dedupe by ``idempotency_key``
    regardless of which vertical the event belongs to.
    """
    loop, publisher, _audit = _make_loop(shipped_catalog)

    def _events() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in _VERTICAL_TRIGGERS.values():
            payload = dict(spec)
            payload.pop("expected_rule_family", None)
            out.append(_event(**payload))
        return out

    # First delivery - every event executes.
    first_results = [await loop.process(event) for event in _events()]
    for result in first_results:
        assert result.outcome is ControlLoopOutcome.EXECUTED
    pr_count_first = len(publisher.records)
    assert pr_count_first >= len(_VERTICAL_TRIGGERS)

    # Second delivery - every event dedupes; PR count MUST NOT grow.
    second_results = [await loop.process(event) for event in _events()]
    for result in second_results:
        assert result.outcome is ControlLoopOutcome.DEDUPED
    assert len(publisher.records) == pr_count_first, (
        "re-delivered events opened new PRs - dedupe regressed"
    )
